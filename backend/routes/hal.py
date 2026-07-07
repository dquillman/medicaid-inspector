"""
HAL relay — proxies "Ask HAL" chat from the MFI frontend to the shared HAL
assistant that lives in the qcode ops app, so MFI does NOT duplicate HAL's
Anthropic tool-loop. The data flow is bidirectional:

    MFI UI  ──/api/hal/chat──▶  this relay  ──▶  qcode /api/hal  ──▶  Anthropic
                                                      │
    MFI backend/mcp_server.py  ◀── HAL calls mfi_* tools over MCP ──┘

qcode's HAL endpoint is admin-gated (Bearer token). We hold that token here
(settings.HAL_TOKEN) so it never reaches the browser; the browser calls this
relay with its normal MFI session, gated by require_user like every other
authenticated MFI route.
"""
import asyncio
import logging
import os
import subprocess
import sys
import time
from typing import List, Literal, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routes.auth import require_user
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hal", tags=["hal"])

# ── HAL (qcode) supervisor ───────────────────────────────────────────────────
# HAL's brain lives in the separate qcode app. If it's closed mid-session the
# relay would just error "offline" until the user restarts it. Instead, when we
# find qcode down we start it (npm run dev in HAL_QCODE_DIR) and wait for it to
# come up — so HAL self-heals without the user touching a terminal.

_qcode_start_lock = asyncio.Lock()
_QCODE_WARMUP_SECONDS = 45  # dev server boot + first compile


def _qcode_base_url() -> str:
    """The origin of the HAL endpoint (e.g. http://localhost:3000/)."""
    u = urlparse(settings.HAL_URL)
    return f"{u.scheme}://{u.netloc}/"


async def _qcode_is_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.get(_qcode_base_url())
        return True
    except Exception:
        return False


def _spawn_qcode(qdir: str) -> None:
    """Start `npm run dev` in the qcode repo, detached so it outlives this
    backend process (and this request) and keeps running for the session."""
    logger.info("HAL offline — auto-starting qcode in %s", qdir)
    try:
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                "npm run dev", cwd=qdir, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags, close_fds=True,
            )
        else:
            subprocess.Popen(
                ["npm", "run", "dev"], cwd=qdir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
    except Exception as e:
        logger.error("Failed to spawn qcode: %s", e)


def _hal_is_local() -> bool:
    """We can only auto-start HAL when HAL_URL points at this machine — you
    can't `npm run dev` a server that lives on Firebase/Cloud Run."""
    host = (urlparse(settings.HAL_URL).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "")


async def _ensure_qcode_running() -> str:
    """Return 'up' (reachable), 'starting' (spawned, not ready yet), or
    'unavailable' (can't auto-start). Single-flight via a lock so concurrent
    requests never spawn more than one qcode."""
    if await _qcode_is_up():
        return "up"
    qdir = settings.HAL_QCODE_DIR
    if not _hal_is_local() or not qdir or not os.path.isdir(qdir):
        return "unavailable"
    async with _qcode_start_lock:
        # Another request may have started it while we waited for the lock.
        if await _qcode_is_up():
            return "up"
        _spawn_qcode(qdir)
        deadline = time.monotonic() + _QCODE_WARMUP_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            if await _qcode_is_up():
                return "up"
        return "starting"


class HalMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class HalChatRequest(BaseModel):
    messages: List[HalMessage]
    # The NPI the user is currently viewing (if any), so HAL can act on it
    # without the user restating it.
    npi: Optional[str] = None
    # Which persona answers. All three live in qcode behind the same admin
    # token and share one tool-loop; only the voice differs. (House rule:
    # every HAL surface must offer the face switcher.)
    face: Literal["assistant", "hal", "jarvis"] = "hal"


# qcode endpoint per face, derived from HAL_URL (which points at .../api/hal).
_FACE_PATHS = {"hal": "/api/hal", "assistant": "/api/ops/chat", "jarvis": "/api/jarvis"}


def _face_url(face: str) -> str:
    base = settings.HAL_URL
    for path in _FACE_PATHS.values():
        if base.endswith(path):
            base = base[: -len(path)]
            break
    return base + _FACE_PATHS.get(face, "/api/hal")


class HalAction(BaseModel):
    name: str
    input: dict = {}
    result: str = ""


class HalProvider(BaseModel):
    npi: str
    name: str


class HalChatResponse(BaseModel):
    reply: str
    actions: List[HalAction] = []
    # Providers referenced in the reply (npi + name) so the UI can linkify names.
    providers: List[HalProvider] = []


@router.get("/status")
async def hal_status(user: dict = Depends(require_user)):
    """Whether HAL is configured — either MFI's own local expert loop
    (ANTHROPIC_API_KEY) or the qcode relay (HAL_TOKEN). The frontend hides the
    Ask HAL panel entirely when neither is set, so a bare deploy shows no dead
    button."""
    from core import hal_expert
    return {"configured": bool(settings.HAL_TOKEN) or hal_expert.available()}


_SLOW_MSG = (
    "HAL took too long to answer (over ~3 minutes). Try again, or ask a narrower "
    "question — big multi-provider sweeps are the slow ones."
)


async def _post_to_hal(url: str, messages: List[dict]) -> httpx.Response:
    """POST one turn to a qcode persona endpoint. Generous read timeout: a
    multi-tool answer is 2-8 Anthropic rounds plus MCP lookups and can exceed
    60s when cold."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=170.0, write=30.0, pool=30.0)
    ) as client:
        return await client.post(
            url,
            json={"messages": messages},
            headers={"Authorization": f"Bearer {settings.HAL_TOKEN}"},
        )


def _inject_provider_context(messages: List[dict], npi: Optional[str]) -> List[dict]:
    """If the user is on a provider page, tell HAL which NPI — prepended to the
    most recent user message so HAL can call its mfi_* tools without the user
    restating the number. Only the latest user turn is annotated; earlier turns
    are left as-is."""
    if not npi:
        return messages
    out = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            out[i]["content"] = (
                f"[Context: I am currently viewing provider NPI {npi} in "
                f"Medicaid Inspector.]\n\n{out[i]['content']}"
            )
            break
    return out


@router.post("/chat", response_model=HalChatResponse)
async def hal_chat(req: HalChatRequest, user: dict = Depends(require_user)):
    """Answer one chat turn. Prefers MFI's OWN local expert loop (its fraud tools
    + a brain_ask into the Second Brain) so this HAL is the expert of THIS app;
    falls back to relaying to qcode's HAL when no ANTHROPIC_API_KEY is set."""
    if not req.messages:
        raise HTTPException(400, "No messages.")

    # App-HAL pattern: run MFI's own expert loop in-process when we can. This is
    # the path that actually reaches the fraud data (top_risky_providers, etc.).
    from core import hal_expert
    if hal_expert.available():
        try:
            out = await hal_expert.run(
                [m.model_dump() for m in req.messages][-20:], req.face, req.npi)
            return {"reply": out.get("reply", ""),
                    "actions": [{"name": n} for n in out.get("actions", [])],
                    "providers": out.get("providers", [])}
        except Exception as e:  # noqa: BLE001 — fall back to the relay on any error
            logger.error("local HAL expert failed, relaying to qcode: %s", e)

    if not settings.HAL_TOKEN:
        raise HTTPException(
            503,
            "HAL is not configured — set ANTHROPIC_API_KEY (for MFI's own expert "
            "HAL) or HAL_TOKEN (to relay to qcode's HAL) in the backend environment.",
        )

    # Keep the payload bounded (qcode trims to the last 16 anyway).
    trimmed = [m.model_dump() for m in req.messages][-20:]
    messages = _inject_provider_context(trimmed, req.npi)

    face_url = _face_url(req.face)
    try:
        resp = await _post_to_hal(face_url, messages)
    except httpx.ConnectError:
        # HAL's brain (qcode) is down — try to bring it back, then retry once.
        state = await _ensure_qcode_running()
        if state == "up":
            try:
                resp = await _post_to_hal(face_url, messages)
            except httpx.ConnectError:
                raise HTTPException(
                    503, "HAL just started but isn't answering yet — try again in a moment."
                )
            except httpx.ReadTimeout:
                raise HTTPException(504, _SLOW_MSG)
        elif state == "starting":
            raise HTTPException(
                503,
                "HAL was asleep — I've woken it. Give it ~20 seconds to warm up, then ask again.",
            )
        else:
            raise HTTPException(
                503,
                "HAL is offline — start the qcode ops server (`npm run dev`), or set "
                "HAL_QCODE_DIR so I can start it for you.",
            )
    except httpx.ReadTimeout:
        raise HTTPException(504, _SLOW_MSG)
    except httpx.HTTPError as e:
        logger.error("HAL relay transport error: %s", type(e).__name__)
        raise HTTPException(502, "Could not reach HAL.")

    if resp.status_code != 200:
        detail = "HAL returned an error."
        try:
            detail = resp.json().get("error") or detail
        except Exception:
            pass
        logger.error("HAL upstream %s: %s", resp.status_code, detail)
        raise HTTPException(502, f"HAL error ({resp.status_code}): {detail}")

    data = resp.json()
    return {"reply": data.get("reply", ""), "actions": data.get("actions", [])}
