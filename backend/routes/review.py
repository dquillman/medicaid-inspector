"""
Review queue API routes.
"""
import io as _io
import csv as _csv
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.review_store import (
    get_review_queue,
    get_review_counts,
    get_review_history,
    update_review_item,
    bulk_update_review_items,
    add_to_review_queue,
    set_queue_status,
    get_review_item,
    QueueStatusError,
    VALID_QUEUE_STATUSES,
    add_case_note,
    redact_case_note,
    get_case_notes,
    CaseNoteError,
    is_stale_case,
    case_stale_days,
    get_stale_cases,
    STALE_CASE_DAYS,
)
from core.store import get_prescanned
from routes.auth import require_user, require_admin

# Only-Brain-Top-10 rule: new additions to the review queue must be a provider
# CURRENTLY on the Fraud Brain's visible top-10 board (the exact cards shown on
# /fraud-brain — api.fraudBrainTop(10) — not the wider top-500 badge cutoff).
# Applies to NEW additions only; existing queue items are grandfathered and
# this never removes or re-checks them. Ranks shift as the Brain recomputes, so
# this is checked live at write time, not cached.
BRAIN_GATE_LIMIT = 10


async def _brain_top_npis(limit: int = BRAIN_GATE_LIMIT) -> set[str]:
    import asyncio
    from services.fraud_brain import get_top_frauds
    result = await asyncio.to_thread(get_top_frauds, limit, False)
    return {p["npi"] for p in result.get("top", [])}

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(require_user)])


_UNSET = object()  # sentinel for "field not provided"


class UpdateReviewBody(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None

    class Config:
        # Allow us to detect which fields were actually sent in the request
        pass


class AddReviewBody(BaseModel):
    npi: str
    status: str = "pending"
    notes: str = ""
    assigned_to: Optional[str] = None


class BulkUpdateBody(BaseModel):
    npis: list[str]
    status: str


class QueueStatusBody(BaseModel):
    new_status: str
    note: str = ""


def _enrich_items(items: list[dict]) -> list[dict]:
    """Attach provider_name, state, data-recency, and stale-case flags from the
    prescan cache. NOTE two distinct 'stale' notions here, deliberately kept
    separate: `stale`/`stale_days` = the CASE going untouched (a workflow nudge);
    `recency` = the DATA age (last claim vs. newest data — is the scheme still
    active). A fresh case can sit on stale data and vice-versa."""
    from services.fraud_brain import months_since, recency_badge, dataset_newest_month_index
    by_npi = {p["npi"]: p for p in get_prescanned()}
    newest = dataset_newest_month_index()  # computed once for the batch
    enriched = []
    for item in items:
        p = by_npi.get(item["npi"], {})
        name  = p.get("provider_name") or (p.get("nppes") or {}).get("name") or ""
        state = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state") or ""
        last_month = p.get("last_month")
        enriched.append({
            **item, "provider_name": name, "state": state,
            "stale": is_stale_case(item),
            "stale_days": case_stale_days(item),
            "last_active_month": last_month or None,
            "data_age_months": months_since(last_month),
            "recency": recency_badge(last_month, newest),
        })
    return enriched


async def _brain_queue_npis() -> set[str]:
    """The set of NPIs that should be VISIBLE in the Review Queue: the Fraud
    Brain's current top-N board, plus any case a human has already actioned
    (queue_status advanced past 'open'). Also FORCES the brain providers in —
    any board NPI missing from the store is added (auto-promotion, actor
    'system:brain-sync'). Providers not in this set stay in the DB (nothing is
    deleted) but are filtered out of the queue view. The Brain is the boss: the
    queue mirrors its board rather than a bulk backfill."""
    from core.review_store import get_review_item
    from core.store import get_provider_by_npi

    top = await _brain_top_npis()
    # Guard against non-provider artifacts (e.g. an all-zeros NPI on the board).
    top = {n for n in top if n and len(n) == 10 and n.isdigit() and n != "0000000000"}

    missing = [n for n in top if not get_review_item(n)]
    if missing:
        provs = []
        for n in missing:
            p = get_provider_by_npi(n) or {}
            provs.append({
                "npi": n,
                "risk_score": p.get("risk_score", 0),
                "flags": p.get("flags", []),
                "total_paid": p.get("total_paid", 0),
                "total_claims": p.get("total_claims", 0),
                "_promoted_by": "system:brain-sync",
            })
        add_to_review_queue(provs)

    # Keep any case a human has moved off the default 'open' state visible even
    # if it later drops off the board, so in-progress work is never hidden.
    actioned = {
        i["npi"] for i in get_review_queue()
        if (i.get("queue_status") or "open") != "open"
    }
    return top | actioned


@router.get("")
async def list_review_queue(
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
):
    from core.oig_store import is_excluded
    visible = await _brain_queue_npis()
    # Queue view = Brain board (+ actioned cases). Off-board items remain in the
    # DB but are hidden here. OIG-excluded providers live on the Excluded page.
    all_items = [
        i for i in get_review_queue(status_filter=status)
        if i.get("npi") in visible and not is_excluded(i.get("npi", ""))[0]
    ]
    enriched  = _enrich_items(all_items)
    total     = len(enriched)
    start     = (page - 1) * limit
    items     = enriched[start: start + limit]
    return {"items": items, "total": total, "page": page}


@router.get("/counts")
async def review_counts():
    # Counts reflect the VISIBLE queue (Brain board + actioned), not the full
    # store of grandfathered-but-hidden items.
    visible = await _brain_queue_npis()
    items = [i for i in get_review_queue() if i.get("npi") in visible]
    counts: dict = {}
    for i in items:
        s = i.get("status", "pending")
        counts[s] = counts.get(s, 0) + 1
    counts["total"] = len(items)
    counts["stale"] = sum(1 for i in items if is_stale_case(i))
    return counts


@router.get("/stale")
async def stale_cases(days: int = STALE_CASE_DAYS):
    """Active cases (open / under_review) untouched for >= `days` — the stale-case
    alert. Scoped to the visible queue (Brain board + actioned)."""
    visible = await _brain_queue_npis()
    items = _enrich_items([i for i in get_stale_cases(days) if i.get("npi") in visible])
    return {"threshold_days": days, "count": len(items), "items": items}


@router.post("/backfill")
async def backfill_review_queue():
    """Populate review queue from the current Fraud Brain top-10. Safe to call
    multiple times — no duplicates added.

    Scoped to the Brain top-10 (not the old RISK_THRESHOLD>10 population) to
    honor the Only-Brain-Top-10 rule even from this bulk path. Note: this
    endpoint isn't currently wired to any frontend button — it exists for
    admin/API use."""
    top_npis = await _brain_top_npis()
    prescanned = get_prescanned()
    flagged = [p for p in prescanned if p.get("npi") in top_npis]
    added = add_to_review_queue(flagged)
    return {"scanned": len(prescanned), "flagged": len(flagged), "added": added,
            "brain_gate_limit": BRAIN_GATE_LIMIT}


@router.get("/export/csv")
async def export_review_csv():
    """Export the full review queue as a CSV download."""
    items = get_review_queue()
    if not items:
        raise HTTPException(404, "Review queue is empty")

    output = _io.StringIO()
    writer = _csv.writer(output)
    writer.writerow(["NPI", "Name", "State", "Risk Score", "Flags", "Total Paid", "Status", "Assigned To", "Notes"])
    for item in sorted(items, key=lambda x: -(x.get("risk_score") or 0)):
        flags = item.get("flags") or []
        flag_names = "; ".join(f.get("signal", "") if isinstance(f, dict) else str(f) for f in flags)
        writer.writerow([
            item.get("npi", ""),
            item.get("provider_name", ""),
            item.get("state", ""),
            f'{item.get("risk_score", 0):.1f}',
            flag_names,
            f'{item.get("total_paid", 0):.2f}',
            item.get("status", ""),
            item.get("assigned_to", ""),
            item.get("notes", ""),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=review_queue_export.csv"},
    )


@router.post("/add")
async def add_single_review(body: AddReviewBody, user: dict = Depends(require_user)):
    """Add a single provider to the review queue (e.g. from watchlist). Returns the created/existing item.

    This is the explicit human promotion gate: an NPI enters the case ledger
    (queue_status='open') only through a deliberate action like this, never by
    merely appearing in the Fraud Brain ranking.
    """
    from core.store import get_provider_by_npi
    actor = user.get("username") or user.get("email") or "user"

    # If already in review queue, just update with the new info
    existing = get_review_item(body.npi)
    if existing:
        update_data: dict = {}
        if body.status and body.status != "pending":
            update_data["status"] = body.status
        if body.notes:
            update_data["notes"] = body.notes
        if body.assigned_to:
            update_data["assigned_to"] = body.assigned_to
        if update_data:
            updated = update_review_item(body.npi, **update_data)
            if updated:
                enriched = _enrich_items([updated])
                return {"item": enriched[0], "already_existed": True}
        enriched = _enrich_items([existing])
        return {"item": enriched[0], "already_existed": True}

    # Only-Brain-Top-10 rule (new additions only — existing items above already
    # returned). Checked live so a rank that shifted since the page loaded is
    # caught here, not just in the (best-effort) frontend disabled state.
    top_npis = await _brain_top_npis()
    if body.npi not in top_npis:
        raise HTTPException(
            400,
            f"NPI {body.npi} is not currently in the Fraud Brain top {BRAIN_GATE_LIMIT}. "
            "Only providers on the Brain board can be added to the Review Queue.",
        )

    # Build a provider dict for add_to_review_queue
    provider_data: dict = {"npi": body.npi, "risk_score": 0, "flags": [], "total_paid": 0, "total_claims": 0,
                           "_promoted_by": actor}
    p = get_provider_by_npi(body.npi)
    if p:
        provider_data["risk_score"] = p.get("risk_score", 0)
        provider_data["flags"] = p.get("flags", [])
        provider_data["total_paid"] = p.get("total_paid", 0)
        provider_data["total_claims"] = p.get("total_claims", 0)

    added = add_to_review_queue([provider_data])
    if added == 0:
        raise HTTPException(409, f"Could not add {body.npi} to review queue")

    # Apply initial status/notes/assigned_to if provided
    item = get_review_item(body.npi)
    if item and (body.status != "pending" or body.notes or body.assigned_to):
        update_review_item(
            body.npi,
            status=body.status if body.status != "pending" else None,
            notes=body.notes or None,
            assigned_to=body.assigned_to if body.assigned_to else ...,
        )
        item = get_review_item(body.npi)

    enriched = _enrich_items([item])
    return {"item": enriched[0], "already_existed": False}


@router.post("/bulk-update")
async def bulk_update_review(body: BulkUpdateBody):
    """Update status for multiple NPIs at once."""
    try:
        count = bulk_update_review_items(body.npis, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": count}


@router.get("/queue-statuses")
async def valid_queue_statuses():
    """The allowed case-ledger states (for the frontend status picker)."""
    return {"statuses": sorted(VALID_QUEUE_STATUSES)}


@router.post("/{npi}/queue-status")
async def set_case_queue_status(npi: str, body: QueueStatusBody, user: dict = Depends(require_user)):
    """Explicit, human-initiated case-ledger status change (the ledger write path).

    This is the deliberate counterpart to drafting a document: recording that a
    tip was filed or a case confirmed is a separate, audited action from
    generating the tip text. The authenticated user is recorded as the actor;
    human-gated transitions (tip_filed / confirmed) are allowed here precisely
    because a person performed them.
    """
    actor = user.get("username") or user.get("email") or "user"
    try:
        updated = set_queue_status(npi, body.new_status, actor=actor, actor_type="user", note=body.note)
    except QueueStatusError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(
            404,
            f"NPI {npi} is not in the review queue. Promote it first (Add to review) "
            "— the ledger status only applies to providers a human has taken on.",
        )
    enriched = _enrich_items([updated])
    return {"item": enriched[0]}


class CaseNoteBody(BaseModel):
    text: str


@router.get("/{npi}/case-notes")
async def list_case_notes(npi: str):
    """The append-only case-note log for an NPI (oldest first)."""
    notes = get_case_notes(npi)
    if notes is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return {"npi": npi, "case_notes": notes}


@router.post("/{npi}/case-notes")
async def append_case_note(npi: str, body: CaseNoteBody, user: dict = Depends(require_user)):
    """Append a note to the case log. Append-only by design — corrections are
    new notes, and only an admin redact (tombstoned) can remove text. The
    authenticated user is recorded as the author."""
    actor = user.get("username") or user.get("email") or "user"
    try:
        entry = add_case_note(npi, body.text, actor=actor, actor_type="user")
    except CaseNoteError as e:
        raise HTTPException(400, str(e))
    if entry is None:
        raise HTTPException(
            404,
            f"NPI {npi} is not in the review queue. Promote it first (Add to review) "
            "— case notes attach to cases a human has taken on.",
        )
    return {"npi": npi, "note": entry}


@router.post("/{npi}/case-notes/{note_id}/redact")
async def redact_note(npi: str, note_id: str, user: dict = Depends(require_admin)):
    """Admin-only: blank a note's text, leaving a tombstone in the log and an
    audit-trail entry. The escape hatch for wrong-provider pastes — never a
    silent delete."""
    actor = user.get("username") or user.get("email") or "admin"
    try:
        entry = redact_case_note(npi, note_id, actor=actor)
    except CaseNoteError as e:
        raise HTTPException(400, str(e))
    if entry is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return {"npi": npi, "note": entry}


@router.get("/{npi}/history")
async def review_history(npi: str):
    """Return the audit trail for a specific NPI."""
    trail = get_review_history(npi)
    if trail is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return {"npi": npi, "audit_trail": trail}


@router.patch("/{npi}")
async def update_review(npi: str, body: UpdateReviewBody):
    # Determine if assigned_to was actually sent in the request body
    raw = body.model_dump(exclude_unset=True)
    assigned_to_arg = raw["assigned_to"] if "assigned_to" in raw else ...
    try:
        updated = update_review_item(
            npi,
            status=body.status,
            notes=body.notes,
            assigned_to=assigned_to_arg,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return updated
