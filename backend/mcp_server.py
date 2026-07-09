"""
MCP (Model Context Protocol) stdio server for Medicaid Inspector (MFI).

Exposes 10 tools over the existing FastAPI route/service functions so an
external app (HAL) can query provider risk, the Fraud Brain ranking,
billing-code reference data, provider networks, OIG/exclusion status, billing
timelines, and drafted OIG-tip narratives without going through HTTP. Eight are
read-only; two write: log_bug appends only to the project's MFIBugs.md log, and
update_queue_status records a case-ledger status change for an NPI already in
the review queue (and REFUSES the human-gated tip_filed/confirmed transitions —
those must come from a human via the UI, never from this AI-side tool).

Run as a subprocess, stdio transport:
    G:/Python311/python.exe G:/Users/daveq/medicaid inspector/backend/mcp_server.py

Working directory MUST be `backend/` (or this file's directory, which is added
to sys.path below) — every import here is the same package-relative import the
FastAPI app itself uses (`from routes.providers import ...`, etc.).

IMPORTANT — this server is a TRUSTED LOCAL SUBPROCESS, not a network service.
None of the wrapped functions re-check `require_user`/`require_admin` — those
FastAPI dependencies are declared at the APIRouter level and only fire inside
the ASGI request cycle, not when the underlying coroutine/function is called
directly in-process (which is what every tool below does). Any stdio-connected
client (HAL) therefore gets full, unauthenticated read access to provider
PHI-adjacent data plus the network/ownership tracer for as long as this
process runs. That's an intentional trade-off for a same-machine trusted
caller, not an oversight — do not expose this process over a network
transport without adding an auth layer first.

No beneficiary-level PHI is ever returned — only provider-aggregate stats and
already-existing evidence/narrative text, matching what the routes themselves
expose.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

# ── Make same-package relative imports (routes.*, core.*, services.*, data.*)
# resolvable regardless of the caller's cwd. ──────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool

# ── Reused service/route functions — imported, never reimplemented ───────────
from routes.providers import (
    get_provider_detail,
    get_timeline,
    provider_signal_evidence,
    provider_oig_tip,
)
from services.slim_cache_enricher import enrich_provider_detail, parquet_is_local
from services.fraud_brain import get_top_frauds
from routes.billing_codes import diagnoses_for_code
from data.cpt_descriptions import CPT_DESCRIPTIONS
from data.icd10_descriptions import ICD10_DESCRIPTIONS
from routes.network import get_network
from core.exclusion_aggregator import check_all_exclusions
from core.phi_logger import log_phi_access, load_phi_log_from_disk
from core.store import load_prescanned_from_disk, get_provider_by_npi
from data.nppes_client import get_provider as nppes_get_provider

from fastapi import HTTPException

_NPI_RE = re.compile(r"^\d{10}$")

# Sentinel PHI-log identity for this process. Override per-caller with
# MCP_CLIENT_ID if per-caller attribution is ever wanted.
_MCP_CLIENT_ID = os.environ.get("MCP_CLIENT_ID", "mcp:hal")

# Network/ownership tool is the one place this server bypasses the HTTP app's
# auth gates AND crosses into cross-provider graph data. Gate it behind an
# explicit opt-in env var so a misconfigured caller can't reach it silently.
_ALLOW_NETWORK_TOOL = os.environ.get("MCP_ALLOW_NETWORK_TOOL", "1") not in ("0", "false", "False")


def _log_phi(action: str, resource_type: str, resource_id: str, **details: Any) -> None:
    """Shared PHI-access logging wrapper — every tool except search_billing_code calls this."""
    log_phi_access(
        user_id=_MCP_CLIENT_ID,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=None,
        details=details or None,
    )


def _require_npi(npi: str) -> str:
    """Validate NPI is exactly 10 digits before it reaches any downstream function.

    Mirrors the same `^\\d{10}$` gate used in routes/network.py and
    routes/providers.py's `_validate_npi` — several downstream functions
    string-interpolate the NPI into SQL post-validation and do not
    independently re-validate it themselves.
    """
    npi = (npi or "").strip()
    if not _NPI_RE.match(npi):
        raise ValueError(f"Invalid NPI '{npi}' — must be exactly 10 digits")
    return npi


# ── Tool 1: get_provider ──────────────────────────────────────────────────────

async def _tool_get_provider(args: dict) -> dict:
    npi = _require_npi(args["npi"])
    signal = args.get("signal")
    include_timeline = bool(args.get("include_timeline", False))

    try:
        result = await get_provider_detail(npi)
    except HTTPException as e:
        raise ValueError(f"get_provider({npi}): {e.detail}") from e

    _log_phi("read", "provider", npi, tool="get_provider")

    if signal:
        try:
            evidence = await provider_signal_evidence(npi, signal)
        except HTTPException as e:
            raise ValueError(f"get_provider({npi}) signal evidence: {e.detail}") from e
        result = {**result, "evidence": evidence}

    if include_timeline:
        if not parquet_is_local():
            result = {**result, "timeline_note": "Local parquet is not available on this deployment — per-HCPCS/monthly timeline detail cannot be computed."}
        else:
            enriched, note = await asyncio.to_thread(enrich_provider_detail, result, include_timeline=True)
            result = enriched
            if note:
                result = {**result, "timeline_note": note}

    return result


# ── Tool 2: top_risky_providers ───────────────────────────────────────────────

async def _tool_top_risky_providers(args: dict) -> dict:
    limit = int(args.get("limit", 10))
    limit = max(1, min(limit, 200))
    state = (args.get("state") or "").strip().upper() or None
    signal = (args.get("signal") or "").strip() or None
    force_refresh = bool(args.get("force_refresh", False))

    # No state/signal filter support in get_top_frauds itself — over-pull, then
    # filter/truncate here in Python (per spec: 5x limit, 100 floor).
    pull_limit = max(limit * 5, 100) if (state or signal) else limit

    result = await asyncio.to_thread(get_top_frauds, pull_limit, force_refresh)

    _log_phi(
        "read", "provider", "batch:top_frauds",
        tool="top_risky_providers", limit=limit, state=state, signal=signal,
    )

    top = result.get("top", [])
    if state:
        top = [e for e in top if (e.get("state") or "").upper() == state]
    if signal:
        # get_top_frauds() entries do NOT carry a per-signal breakdown for the
        # full ~18-key fraud-signal vocabulary (_SIGNAL_META in this same
        # routes/providers.py module) — evidence[].source is human-readable
        # prose ("OIG LEIE exclusion", "Size adjustment", ...) and components
        # only has the six internal scoring buckets (rule_signals, ml_anomaly,
        # corroboration, dollars, flag_breadth, supervised_ml). Neither is the
        # per-rule-signal key vocabulary a caller would reasonably pass here.
        # Only "oig_excluded" has a real, directly-matching boolean already on
        # the entry (fraud_brain.py's `entry["oig_excluded"]`) — support that
        # one exactly, and fail loudly (not silently-empty) for anything else
        # so a typo'd/unsupported signal key can't look like "zero matches".
        # Per-rule-signal evidence for the OTHER 17 keys IS available, just not
        # here — use get_provider(npi, signal=...) instead, which calls
        # provider_signal_evidence() and returns the real methodology/proof.
        if signal != "oig_excluded":
            raise ValueError(
                f"top_risky_providers does not support filtering by signal='{signal}'. "
                "Only 'oig_excluded' is supported here (it's the one signal with a "
                "direct per-entry flag). For evidence on any other fraud signal "
                "(e.g. 'dead_npi_billing', 'billing_concentration', 'upcoding_pattern'), "
                "call get_provider with that NPI and signal=<key> instead."
            )
        top = [e for e in top if e.get("oig_excluded")]

    top = top[:limit]

    # Backfill missing identity fields. Many prescan-cache rows have no
    # provider_name/state/specialty (the slim cache stores only billing stats),
    # which left HAL answering with bare NPIs. Best-effort NPPES lookup (cached
    # via @cached_nppes) for just the entries being returned — never fails the
    # tool if the registry is slow or down.
    async def _fill(entry: dict) -> None:
        if entry.get("provider_name") and entry.get("state"):
            return
        try:
            info = await nppes_get_provider(entry.get("npi", ""))
        except Exception:
            return
        if not info:
            return
        if not entry.get("provider_name"):
            entry["provider_name"] = info.get("name", "")
        if not entry.get("state"):
            entry["state"] = (info.get("address") or {}).get("state", "")
        if not entry.get("specialty"):
            entry["specialty"] = (info.get("taxonomy") or {}).get("description", "")

    await asyncio.gather(*(_fill(e) for e in top), return_exceptions=True)

    return {**result, "top": top, "filters": {"state": state, "signal": signal}}


# ── Tool 3: search_billing_code ───────────────────────────────────────────────

def _search_codes(query: str, code_set: str, limit: int) -> list[dict]:
    """Replicates routes.billing_codes.search_icd10's loop generically over
    CPT_DESCRIPTIONS and/or ICD10_DESCRIPTIONS (both plain dict[str,str],
    imported — not recreated). No existing standalone function covers CPT, and
    none covers "both" — this is new glue code over reused data, per spec."""
    q_upper = query.strip().upper()
    q_lower = query.strip().lower()
    results: list[dict] = []

    sources: list[tuple[str, dict]] = []
    if code_set in ("cpt", "both"):
        sources.append(("cpt", CPT_DESCRIPTIONS))
    if code_set in ("icd10", "both"):
        sources.append(("icd10", ICD10_DESCRIPTIONS))

    for set_name, table in sources:
        for code, desc in table.items():
            if code.upper().startswith(q_upper) or q_lower in desc.lower():
                results.append({"code_set": set_name, "code": code, "description": desc})
                if len(results) >= limit:
                    return results
    return results


async def _tool_search_billing_code(args: dict) -> dict:
    code_set = args.get("code_set", "both")
    if code_set not in ("cpt", "icd10", "both"):
        raise ValueError(f"Invalid code_set '{code_set}' — must be one of cpt, icd10, both")
    limit = int(args.get("limit", 30))
    limit = max(1, min(limit, 100))

    diagnoses_for = (args.get("diagnoses_for_code") or "").strip()
    if diagnoses_for:
        return await diagnoses_for_code(diagnoses_for)

    query = (args.get("query") or "").strip()
    if not query:
        raise ValueError("Provide either 'query' or 'diagnoses_for_code'")

    results = _search_codes(query, code_set, limit)
    return {"query": query, "code_set": code_set, "results": results, "total": len(results)}
    # No log_phi_access call — pure public reference data, no provider/beneficiary PHI.


# ── Tool 4: provider_network ──────────────────────────────────────────────────

async def _tool_provider_network(args: dict) -> dict:
    if not _ALLOW_NETWORK_TOOL:
        raise ValueError(
            "provider_network is disabled on this server (MCP_ALLOW_NETWORK_TOOL=0). "
            "This tool bypasses the HTTP app's auth gates and exposes cross-provider "
            "network/ownership data — enable only for a fully trusted caller."
        )

    npi = _require_npi(args["npi"])
    include_billing_network = bool(args.get("include_billing_network", True))
    include_ownership = bool(args.get("include_ownership", True))

    out: dict = {"npi": npi}

    if include_billing_network:
        try:
            out["billing_network"] = await get_network(npi)
        except HTTPException as e:
            if e.status_code == 504:
                out["billing_network_error"] = (
                    "network computation still running server-side, retry shortly "
                    f"(NPI {npi} has too large a network to compute within the timeout window)"
                )
            else:
                out["billing_network_error"] = f"{e.status_code}: {e.detail}"

    if include_ownership:
        from services.ownership_tracer import trace_ownership_network_async
        out["ownership"] = await trace_ownership_network_async(npi)

    _log_phi("read", "provider", npi, tool="provider_network")
    return out


# ── Tool 5: oig_status ────────────────────────────────────────────────────────

async def _tool_oig_status(args: dict) -> dict:
    npi = _require_npi(args["npi"])
    name = args.get("name", "") or ""

    result = await check_all_exclusions(npi, name)
    _log_phi("read", "provider", npi, tool="oig_status")
    return result


# ── Tool 6: provider_timeline ─────────────────────────────────────────────────

async def _tool_provider_timeline(args: dict) -> dict:
    npi = _require_npi(args["npi"])
    try:
        result = await get_timeline(npi)
    except HTTPException as e:
        raise ValueError(f"provider_timeline({npi}): {e.detail}") from e

    _log_phi("read", "provider", npi, tool="provider_timeline")
    return result


# ── Tool 7: draft_oig_tip ─────────────────────────────────────────────────────

async def _tool_draft_oig_tip(args: dict) -> dict:
    npi = _require_npi(args["npi"])
    try:
        result = await provider_oig_tip(npi)
    except HTTPException as e:
        raise ValueError(f"draft_oig_tip({npi}): {e.detail}") from e

    # resource_type="evidence" (not "provider") — the output is a compiled
    # evidentiary document (dossier), which fits the taxonomy better than a
    # raw provider read. action="draft" since this generates rather than reads.
    _log_phi("draft", "evidence", npi, tool="draft_oig_tip")
    return result


# ── Tool registry ─────────────────────────────────────────────────────────────

_NPI_SCHEMA = {"type": "string", "pattern": r"^\d{10}$", "description": "10-digit National Provider Identifier"}

TOOLS: list[Tool] = [
    Tool(
        name="get_provider",
        description=(
            "Get full detail for a single provider by NPI, including risk score, all fraud "
            "signal results, NPPES profile, and spending summary. Optionally include detailed "
            "evidence for one specific fraud signal, and/or per-HCPCS/monthly timeline detail."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "npi": _NPI_SCHEMA,
                "signal": {
                    "type": "string",
                    "description": "Optional: if set, also return detailed evidence (methodology/threshold/proof numbers) for this specific fraud signal key",
                },
                "include_timeline": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, also attempt to enrich with per-HCPCS/monthly timeline detail (only works if local parquet is available; otherwise a note is returned instead)",
                },
            },
            "required": ["npi"],
        },
    ),
    Tool(
        name="top_risky_providers",
        description='Get the ranked list of highest-risk providers (the "Fraud Brain"), optionally filtered by state or fraud signal.',
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 200, "description": "Number of results to return after filtering"},
                "state": {"type": "string", "description": "Optional 2-letter state code to filter results (e.g. 'NY')"},
                "signal": {"type": "string", "description": "Optional: only 'oig_excluded' is supported (filters to OIG-excluded providers). Any other value raises an error — for evidence on other fraud signals, call get_provider with signal=<key> instead."},
                "force_refresh": {"type": "boolean", "default": False, "description": "Bypass the 15-minute cache and recompute"},
            },
            "required": [],
        },
    ),
    Tool(
        name="search_billing_code",
        description="Search CPT/HCPCS or ICD-10 billing codes by code prefix or description text, or look up ICD-10 diagnoses commonly crosswalked to a specific CPT/HCPCS code.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Code prefix or description substring to search for"},
                "code_set": {"type": "string", "enum": ["cpt", "icd10", "both"], "default": "both", "description": "Which code set to search"},
                "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 100},
                "diagnoses_for_code": {"type": "string", "description": "Optional: if set (a specific HCPCS/CPT code), return the ICD-10 diagnoses crosswalked to it instead of doing a text search"},
            },
            "required": [],
        },
    ),
    Tool(
        name="provider_network",
        description="Get the billing relationship network (connected NPIs by referral/servicing patterns) and/or ownership connections (shared authorized official, address, phone) for a provider.",
        inputSchema={
            "type": "object",
            "properties": {
                "npi": _NPI_SCHEMA,
                "include_billing_network": {"type": "boolean", "default": True, "description": "Include the billing/servicing relationship graph"},
                "include_ownership": {"type": "boolean", "default": True, "description": "Include shared-official/address/phone ownership connections"},
            },
            "required": ["npi"],
        },
    ),
    Tool(
        name="oig_status",
        description="Check whether a provider is OIG-excluded (LEIE) and/or has a deactivated NPI.",
        inputSchema={
            "type": "object",
            "properties": {
                "npi": _NPI_SCHEMA,
                "name": {"type": "string", "default": "", "description": "Optional provider name to improve match confidence"},
            },
            "required": ["npi"],
        },
    ),
    Tool(
        name="provider_timeline",
        description="Get a provider's monthly billing timeline (claims, paid amount, unique beneficiaries per month).",
        inputSchema={
            "type": "object",
            "properties": {"npi": _NPI_SCHEMA},
            "required": ["npi"],
        },
    ),
    Tool(
        name="draft_oig_tip",
        description="Generate a draft HHS-OIG hotline complaint narrative for a provider from cached fraud signal evidence. Drafting only — does not submit anything to HHS or any external system.",
        inputSchema={
            "type": "object",
            "properties": {"npi": _NPI_SCHEMA},
            "required": ["npi"],
        },
    ),
    Tool(
        name="data_freshness",
        description="Report when each exclusion data source (OIG LEIE, SAM.gov, NPPES) was last successfully updated, its record count, and refresh cadence. Use for questions like 'how current is the SAM data' or 'when was the exclusion list last updated'.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="log_bug",
        description=(
            "Append a bug report to the project's MFIBugs.md log. Use when the user reports "
            "a bug, defect, or something broken in the app and wants it recorded. Writes a "
            "structured, timestamp-stamped entry to the repo file. Locally this persists to "
            "the real file for the user to commit; on the deployed (Cloud Run) instance the "
            "filesystem is ephemeral, so the entry is best-effort and won't survive a restart "
            "— the response says which case applied."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short one-line summary of the bug"},
                "detail": {"type": "string", "description": "What's wrong: symptom, expected vs actual, impact"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
                "npi": {"type": "string", "description": "Optional NPI used to reproduce, if provider-specific"},
                "area": {"type": "string", "description": "Optional area/page/feature the bug is in (e.g. 'Referral Packet', 'Provider Detail')"},
            },
            "required": ["title"],
        },
    ),
    Tool(
        name="update_queue_status",
        description=(
            "Record a case-ledger status change for an NPI that is ALREADY in the review "
            "queue (open / under_review / tip_filed / dismissed / confirmed / referred). This "
            "is a DISTINCT, deliberately-separate action from draft_oig_tip: drafting a tip "
            "generates text; it does NOT record that a tip was filed. Recording that is this "
            "tool. IMPORTANT: the weighty transitions 'tip_filed' and 'confirmed' require a "
            "human and are REFUSED here — a person must do those from the review UI, so an AI "
            "cannot mark a tip filed or a case confirmed as a side effect. Does not add NPIs to "
            "the queue (promotion is a separate human action) and never changes the risk score."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "npi": _NPI_SCHEMA,
                "new_status": {"type": "string", "enum": sorted(
                    ["open", "under_review", "tip_filed", "dismissed", "confirmed", "referred"])},
                "note": {"type": "string", "description": "Optional reason/context recorded in the audit trail"},
            },
            "required": ["npi", "new_status"],
        },
    ),
]


async def _tool_data_freshness(args: dict) -> dict:
    import os
    from core.oig_store import get_oig_stats
    from core.sam_extract_store import status as sam_status, ensure_loaded
    try:
        await ensure_loaded()
    except Exception:
        pass
    oig = get_oig_stats()
    sam = sam_status()
    _log_phi("read", "system", "data_freshness", tool="data_freshness")
    return {
        "oig_leie": {"loaded": oig.get("loaded", False),
                     "record_count": oig.get("record_count", 0),
                     "source": "OIG LEIE (local monthly CSV)"},
        "sam": {**sam, "mode": "live API + extract fallback" if os.environ.get("SAM_API_KEY")
                else "public extract (keyless)"},
        "nppes": {"mode": "live registry lookup on demand (keyless)"},
    }


# ── Tool 9: log_bug ───────────────────────────────────────────────────────────

# MFIBugs.md lives at the repo root — one level up from backend/.
_BUGLOG_PATH = _BACKEND_DIR.parent / "MFIBugs.md"


async def _tool_log_bug(args: dict) -> dict:
    """Append a structured bug entry to MFIBugs.md.

    This is the ONE write tool this server exposes. It only ever appends to a
    single fixed project file (never an arbitrary path), and every field is
    ASCII-sanitized before it touches the file — same reason the OIG tip is
    sanitized: a bug title pasted from a chat may carry curly quotes/em-dashes,
    and the log is a plain-text/markdown artifact meant to be committed.
    """
    from core.text_sanitize import to_ascii
    from datetime import datetime, timezone

    title = to_ascii((args.get("title") or "").strip())
    if not title:
        raise ValueError("log_bug: 'title' is required")
    detail = to_ascii((args.get("detail") or "").strip())
    severity = (args.get("severity") or "medium").strip().lower()
    if severity not in ("low", "medium", "high", "critical"):
        severity = "medium"
    npi = _require_npi(args["npi"]) if args.get("npi") else ""
    area = to_ascii((args.get("area") or "").strip())

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"\n### {title}",
        f"- **Logged:** {ts} (via HAL)",
        f"- **Severity:** {severity}",
    ]
    if area:
        lines.append(f"- **Area:** {area}")
    if npi:
        lines.append(f"- **Repro NPI:** {npi}")
    if detail:
        lines.append(f"- **Detail:** {detail}")
    lines.append(f"- **Status:** OPEN")
    entry = "\n".join(lines) + "\n"

    _HEADER = ("# MFI Bug Log\n\nBugs logged via HAL and manual entry. "
               "Newest entries appended below.\n")

    def _try_append(path: Path) -> bool:
        try:
            if not path.exists():
                path.write_text(_HEADER, encoding="utf-8")
            with path.open("a", encoding="utf-8") as f:
                f.write(entry)
            return True
        except OSError:
            return False

    # Best target first: the committable repo file. On Cloud Run that lives under
    # a read-only root (/MFIBugs.md -> Errno 13), so fall back to a writable temp
    # path — best-effort capture for the session. This tool must NEVER raise on a
    # write failure (its whole contract is graceful degradation); if every target
    # is unwritable we return logged=False and hand the formatted entry back so
    # the caller can relay it to Dave for manual capture.
    import tempfile

    tmp_path = Path(tempfile.gettempdir()) / "MFIBugs.md"
    targets = [_BUGLOG_PATH] + ([tmp_path] if tmp_path != _BUGLOG_PATH else [])
    written_to = next((p for p in targets if _try_append(p)), None)

    _log_phi("write", "system", "MFIBugs.md", tool="log_bug",
             title=title, severity=severity, persisted=bool(written_to))

    if written_to is None:
        return {
            "logged": False,
            "persisted": False,
            "title": title,
            "severity": severity,
            "entry": entry.strip(),
            "note": ("Could not write MFIBugs.md on this deployment (read-only "
                     "filesystem). Nothing was persisted. Relay the 'entry' text "
                     "to Dave so it can be added to MFIBugs.md from a local session."),
        }

    persisted = written_to == _BUGLOG_PATH  # only the repo file is committable
    note = (
        "Logged to MFIBugs.md in the local repo. Commit the file to keep the entry."
        if persisted else
        f"This deployment's repo path is read-only, so the entry was written to a "
        f"temporary file ({written_to}) and will NOT survive a restart or reach the "
        f"repo. Relay it to Dave to persist it from a local session."
    )
    return {"logged": True, "file": str(written_to), "title": title,
            "severity": severity, "persisted": persisted, "entry": entry.strip(),
            "note": note}


# ── Tool 10: update_queue_status ──────────────────────────────────────────────

async def _tool_update_queue_status(args: dict) -> dict:
    """Record a case-ledger status change. AI/MCP callers act with
    actor_type='ai', so the human-gated transitions (tip_filed / confirmed) are
    refused by the store — this is the enforcement point for "no AI-recorded tip
    filing / case confirmation." Never adds an NPI to the queue."""
    from core.review_store import set_queue_status, QueueStatusError

    npi = _require_npi(args["npi"])
    new_status = str(args.get("new_status", "")).strip()
    note = str(args.get("note", "")).strip()
    try:
        updated = set_queue_status(
            npi, new_status, actor=_MCP_CLIENT_ID, actor_type="ai", note=note,
        )
    except QueueStatusError as e:
        # Surface the refusal/validation message to the model verbatim.
        raise ValueError(str(e)) from e
    if updated is None:
        raise ValueError(
            f"NPI {npi} is not in the review queue. Promotion into the queue is a "
            "separate human action; this tool only changes the status of NPIs "
            "already promoted."
        )
    _log_phi("write", "case", npi, tool="update_queue_status", new_status=new_status)
    return {
        "npi": npi,
        "queue_status": updated.get("queue_status"),
        "updated_at": updated.get("queue_status_updated_at"),
        "actor_type": "ai",
    }


_HANDLERS = {
    "get_provider": _tool_get_provider,
    "top_risky_providers": _tool_top_risky_providers,
    "search_billing_code": _tool_search_billing_code,
    "provider_network": _tool_provider_network,
    "oig_status": _tool_oig_status,
    "provider_timeline": _tool_provider_timeline,
    "draft_oig_tip": _tool_draft_oig_tip,
    "data_freshness": _tool_data_freshness,
    "log_bug": _tool_log_bug,
    "update_queue_status": _tool_update_queue_status,
}


def _bootstrap_state() -> None:
    """Load the same on-disk state the FastAPI app's lifespan() loads at startup
    (minus GCS sync / OIG download / NPPES enrichment, which are network-bound
    background jobs) — so get_provider_by_npi() and friends return real data
    instead of hitting a cold, empty in-memory store.

    Loads the full local cache when present (matches local-dev behavior in
    main.py's lifespan), else falls back to the slim Cloud Run cache.
    """
    loaded = load_prescanned_from_disk()  # full prescan_cache.json
    if not loaded:
        loaded = load_prescanned_from_disk("prescan_slim.json")
    load_phi_log_from_disk()
    print(
        f"[mcp_server] Bootstrapped: providers_loaded={loaded}, "
        f"parquet_local={parquet_is_local()}",
        file=sys.stderr,
    )


async def main() -> None:
    _bootstrap_state()

    server = Server("mfi-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> dict:
        handler = _HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool '{name}'")
        return await handler(arguments or {})

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mfi-mcp",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
