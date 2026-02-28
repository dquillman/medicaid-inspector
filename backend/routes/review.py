"""
Review queue API routes.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.review_store import (
    get_review_queue,
    get_review_counts,
    update_review_item,
    bulk_update_review_items,
    add_to_review_queue,
)
from core.store import get_prescanned
from core.config import settings

router = APIRouter(prefix="/api/review", tags=["review"])


class UpdateReviewBody(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


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
    flagged = [p for p in prescanned if p.get("risk_score", 0) >= settings.RISK_THRESHOLD]
    added = add_to_review_queue(flagged)
    return {"scanned": len(prescanned), "flagged": len(flagged), "added": added, "threshold": settings.RISK_THRESHOLD}


@router.post("/bulk-update")
async def bulk_update_review(body: BulkUpdateBody):
    """Update status for multiple NPIs at once."""
    try:
        count = bulk_update_review_items(body.npis, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": count}


@router.patch("/{npi}")
async def update_review(npi: str, body: UpdateReviewBody):
    try:
        updated = update_review_item(npi, status=body.status, notes=body.notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return updated
