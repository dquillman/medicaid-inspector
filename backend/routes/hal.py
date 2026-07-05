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
import logging
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routes.auth import require_user
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hal", tags=["hal"])


class HalMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class HalChatRequest(BaseModel):
    messages: List[HalMessage]
    # The NPI the user is currently viewing (if any), so HAL can act on it
    # without the user restating it.
    npi: Optional[str] = None


class HalAction(BaseModel):
    name: str
    input: dict = {}
    result: str = ""


class HalChatResponse(BaseModel):
    reply: str
    actions: List[HalAction] = []


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
    """Relay one chat turn to HAL and return its reply + the tools it used."""
    if not settings.HAL_TOKEN:
        raise HTTPException(
            503,
            "HAL is not configured — set HAL_TOKEN (the qcode admin token) in the "
            "backend environment to enable the Ask HAL panel.",
        )
    if not req.messages:
        raise HTTPException(400, "No messages.")

    # Keep the payload bounded (qcode trims to the last 16 anyway).
    trimmed = [m.model_dump() for m in req.messages][-20:]
    messages = _inject_provider_context(trimmed, req.npi)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                settings.HAL_URL,
                json={"messages": messages},
                headers={"Authorization": f"Bearer {settings.HAL_TOKEN}"},
            )
    except httpx.ConnectError:
        raise HTTPException(
            503,
            "HAL is offline — start the qcode ops server (run `npm run dev` in the "
            "qcode repo, or set HAL_URL to its address).",
        )
    except httpx.HTTPError as e:
        logger.error("HAL relay transport error: %s", e)
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
