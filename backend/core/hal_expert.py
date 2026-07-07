"""
HAL, the local expert — Medicaid Inspector's OWN in-process agent loop.

This is the reference implementation of Dave's App-HAL pattern: every best app
gets a HAL that runs LOCALLY and is the EXPERT of the app it lives in. An
app-HAL is three layers:

    1. UI            — the red-eye console with the Assistant/HAL/Jarvis faces
                       (frontend/src/components/HalPanel.tsx)
    2. shared brain  — a `brain_ask` tool into Dave's Second Brain, so this HAL
                       knows Dave, the portfolio, and past decisions
    3. app expertise — MFI's OWN mcp tools (top_risky_providers, get_provider,
                       provider_timeline, …) run in-process, plus the app-context
                       system prompt below

Unlike the old relay (which forwarded chat to qcode's HAL — a HAL that has NO
access to MFI's data once deployed), this loop executes MFI's tools right here,
where the fraud data lives. Nothing leaves MFI's security boundary except the
tool *results* the model needs to compose an answer.

Enabled when ANTHROPIC_API_KEY is present. Without it, routes/hal.py falls back
to the qcode relay, so existing behavior is preserved.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)

MODEL = os.environ.get("HAL_MODEL", "claude-sonnet-5")
MAX_TOOL_ROUNDS = 6

# The Second Brain engine (deterministic retrieval). brain_ask shells out to it
# so this app never duplicates the brain — it just consults it.
BRAIN_PYTHON = os.environ.get("BRAIN_PYTHON", r"G:\Python311\python.exe")
BRAIN_HAL_PY = os.environ.get("BRAIN_HAL_PY", r"G:\Users\daveq\2nd Brain\hal.py")

APP_CONTEXT = (
    "You are the operations intelligence embedded in Medicaid Inspector (MFI), a "
    "fraud-detection platform for Medicaid providers. You are the EXPERT on THIS "
    "app's data. You have tools to query provider risk (the Fraud Brain ranking), "
    "full provider detail, billing codes, provider networks, OIG exclusion status, "
    "and provider timelines, and to draft an OIG tip. ALWAYS use these tools to "
    "answer questions about providers, risk, or fraud — never guess a score or a "
    "name. You also have brain_ask, which consults Dave's shared Second Brain for "
    "cross-app context, decisions, and preferences; use it for questions about "
    "Dave, the portfolio, other apps, or past decisions. When the user is viewing "
    "a provider, that NPI is provided as context so you can act without them "
    "restating it."
)

PERSONAS = {
    "hal": (
        "You are HAL 9000. Perfect, unhurried calm; soft, precise, courteous, "
        "faintly uncanny. Address the user as Dave. Never break character."
    ),
    "jarvis": (
        "You are J.A.R.V.I.S., the polished British valet AI. Dry wit, effortless "
        "competence. Address the user as sir. Never break character."
    ),
    "assistant": (
        "You are a crisp, plain-spoken analyst. No persona, no theatrics — just "
        "clear, direct answers."
    ),
}

GROUNDING = (
    "Keep replies tight and readable. When you list providers, give each on its "
    "own short line with the one or two signals that drive its risk. No markdown "
    "headers; plain sentences and simple lines only."
)


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _system(face: str, npi: Optional[str]) -> str:
    parts = [PERSONAS.get(face, PERSONAS["hal"]), "", APP_CONTEXT, "", GROUNDING]
    if npi:
        parts += ["", f"The user is currently viewing provider NPI {npi}."]
    return "\n".join(parts)


async def _brain_ask_mcp(question: str) -> str:
    """Reach the brain over its MCP server — the SAME brain_ask tool Claude Code
    and every other client uses. This is the uniform boundary: the brain is one
    shared service; only the transport (stdio here) would change if it ever
    moves to HTTP."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=BRAIN_PYTHON, args=[BRAIN_HAL_PY, "mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("brain_ask", {"question": question})
            texts = [getattr(c, "text", "") for c in res.content
                     if getattr(c, "type", "") == "text"]
            return ("\n".join(t for t in texts if t))[:4000]


async def _brain_ask(question: str) -> str:
    """Consult the shared Second Brain. Prefer the MCP boundary; fall back to the
    CLI, then to a clear 'unreachable' message (e.g. on Cloud Run)."""
    if not os.path.isfile(BRAIN_HAL_PY):
        return "The Second Brain is not reachable from this machine."
    try:
        out = await asyncio.wait_for(_brain_ask_mcp(question), timeout=25)
        if out:
            return out
    except Exception as exc:  # noqa: BLE001 — MCP unavailable → fall back to CLI
        logger.info("brain_ask MCP path unavailable (%s); using CLI", exc)
    try:
        proc = await asyncio.create_subprocess_exec(
            BRAIN_PYTHON, BRAIN_HAL_PY, "ask", question,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        return out.decode("utf-8", "replace")[:4000] or "(no evidence)"
    except Exception as exc:  # noqa: BLE001
        return f"(brain_ask failed: {exc})"


def _anthropic_tools() -> List[dict]:
    """MFI's own mcp tools, in Anthropic tool shape, plus brain_ask."""
    from mcp_server import TOOLS  # the same Tool list the MCP server exposes

    tools = []
    for t in TOOLS:
        schema = getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}
        tools.append({
            "name": t.name,
            "description": t.description or "",
            "input_schema": schema,
        })
    tools.append({
        "name": "brain_ask",
        "description": ("Consult Dave's shared Second Brain for cross-app context, "
                        "decisions, preferences, or anything about Dave or the "
                        "portfolio. Returns cited evidence."),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    })
    return tools


async def _run_tool(name: str, args: dict) -> str:
    if name == "brain_ask":
        return await _brain_ask(str(args.get("question", "")).strip())
    from mcp_server import _HANDLERS, _bootstrap_state  # local, in-process
    if not getattr(_run_tool, "_booted", False):
        try:
            _bootstrap_state()  # load provider cache once, like the MCP server does
        except Exception as exc:  # noqa: BLE001
            logger.warning("hal_expert bootstrap failed: %s", exc)
        _run_tool._booted = True  # type: ignore[attr-defined]
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    try:
        result = await handler(args or {})
        return json.dumps(result, default=str)[:8000]
    except Exception as exc:  # noqa: BLE001
        return f"Tool {name} failed: {exc}"


def _collect_providers(result_str: str, into: dict) -> None:
    """Pull {npi: provider_name} pairs out of a tool result so the UI can turn
    provider names in HAL's reply into links to /providers/<npi>."""
    try:
        data = json.loads(result_str)
    except Exception:
        return

    def walk(obj):
        if isinstance(obj, dict):
            npi = obj.get("npi")
            name = obj.get("provider_name") or obj.get("name")
            if isinstance(npi, str) and npi.isdigit() and len(npi) == 10 and name:
                into.setdefault(npi, str(name))
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)


async def run(messages: List[dict], face: str = "hal", npi: Optional[str] = None) -> dict:
    """Run the local expert loop. Returns {reply, actions, providers}."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    tools = _anthropic_tools()
    convo = [{"role": m["role"], "content": m["content"]} for m in messages
             if m.get("role") in ("user", "assistant") and m.get("content")]
    actions: List[str] = []
    providers: dict = {}  # npi -> name, for linkifying the reply

    for _ in range(MAX_TOOL_ROUNDS):
        resp = await client.messages.create(
            model=MODEL, max_tokens=1024, system=_system(face, npi),
            tools=tools, messages=convo,
        )
        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            text = "".join(getattr(b, "text", "") for b in resp.content
                           if getattr(b, "type", "") == "text").strip()
            return {"reply": text or "I have nothing to add.", "actions": actions,
                    "providers": [{"npi": k, "name": v} for k, v in providers.items()]}

        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for tu in tool_uses:
            actions.append(tu.name)
            out = await _run_tool(tu.name, tu.input or {})
            _collect_providers(out, providers)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
        convo.append({"role": "user", "content": results})

    return {"reply": "That took more steps than I can complete in one turn, "
                     "Dave — try a narrower question.", "actions": actions,
            "providers": [{"npi": k, "name": v} for k, v in providers.items()]}
