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
)
from core.store import get_prescanned
from core.config import settings
from routes.auth import require_user

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(require_user)])


_UNSET = object()  # sentinel for "field not provided"


class UpdateReviewBody(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None

    class Config:
        # Allow us to detect which fields were actually sent in the request
        pass


class BulkUpdateBody(BaseModel):
    npis: list[str]
    status: str


def _enrich_items(items: list[dict]) -> list[dict]:
    """Attach provider_name and state from prescan cache."""
    by_npi = {p["npi"]: p for p in get_prescanned()}
    enriched = []
    for item in items:
        p = by_npi.get(item["npi"], {})
        name  = p.get("provider_name") or (p.get("nppes") or {}).get("name") or ""
        state = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state") or ""
        enriched.append({**item, "provider_name": name, "state": state})
    return enriched


@router.get("")
async def list_review_queue(
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
):
    all_items = get_review_queue(status_filter=status)
    enriched  = _enrich_items(all_items)
    total     = len(enriched)
    start     = (page - 1) * limit
    items     = enriched[start: start + limit]
    return {"items": items, "total": total, "page": page}


@router.get("/counts")
async def review_counts():
    return get_review_counts()


@router.post("/backfill")
async def backfill_review_queue():
    """Populate review queue from existing prescan cache. Safe to call multiple times — no duplicates added."""
    prescanned = get_prescanned()
    flagged = [p for p in prescanned if p.get("risk_score", 0) > settings.RISK_THRESHOLD]
    added = add_to_review_queue(flagged)
    return {"scanned": len(prescanned), "flagged": len(flagged), "added": added, "threshold": settings.RISK_THRESHOLD}


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


@router.post("/bulk-update")
async def bulk_update_review(body: BulkUpdateBody):
    """Update status for multiple NPIs at once."""
    try:
        count = bulk_update_review_items(body.npis, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": count}


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
