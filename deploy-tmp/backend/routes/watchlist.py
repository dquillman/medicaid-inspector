"""
Provider Watchlist API routes.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.watchlist_store import (
    get_watchlist,
    get_watchlist_item,
    add_to_watchlist,
    remove_from_watchlist,
    update_entry,
    is_watched,
)
from core.store import get_prescanned, get_provider_by_npi
from routes.auth import require_user

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"], dependencies=[Depends(require_user)])


class AddToWatchlistBody(BaseModel):
    npi: str
    reason: str = ""
    alert_threshold: float = 50.0
    notes: str = ""


class UpdateWatchlistBody(BaseModel):
    notes: Optional[str] = None
    alert_threshold: Optional[float] = None
    active: Optional[bool] = None
    reason: Optional[str] = None
    reviewing: Optional[bool] = None


def _enrich_with_scan_data(entry: dict) -> dict:
    """Cross-reference watchlist entry with prescan cache for current risk score and details."""
    enriched = dict(entry)
    p = get_provider_by_npi(entry["npi"])
    if p:
        enriched["risk_score"] = p.get("risk_score", 0)
        enriched["total_paid"] = p.get("total_paid", 0)
        enriched["total_claims"] = p.get("total_claims", 0)
        enriched["flag_count"] = len([f for f in p.get("flags", []) if f.get("flagged")])
        if not enriched.get("name"):
            enriched["name"] = p.get("provider_name", "")
        if not enriched.get("specialty"):
            enriched["specialty"] = p.get("specialty", "")
        enriched["state"] = p.get("state", "")
        enriched["city"] = p.get("city", "")
    else:
        enriched.setdefault("risk_score", None)
        enriched.setdefault("total_paid", None)
        enriched.setdefault("total_claims", None)
        enriched.setdefault("flag_count", None)
    # Compute alert status
    risk = enriched.get("risk_score")
    threshold = enriched.get("alert_threshold", 50)
    enriched["in_alert"] = risk is not None and risk >= threshold
    return enriched


@router.get("")
async def list_watchlist():
    """List all watched providers with their current risk scores."""
    items = get_watchlist()
    enriched = [_enrich_with_scan_data(item) for item in items]
    alert_count = sum(1 for e in enriched if e.get("in_alert"))
    return {"items": enriched, "total": len(enriched), "alert_count": alert_count}


@router.post("")
async def add_provider(body: AddToWatchlistBody):
    """Add a provider to the watchlist."""
    # Try to get name/specialty from prescan cache
    name = ""
    specialty = ""
    p = get_provider_by_npi(body.npi)
    if p:
        name = p.get("provider_name", "")
        specialty = p.get("specialty", "")

    entry = add_to_watchlist(
        npi=body.npi,
        name=name,
        specialty=specialty,
        reason=body.reason,
        alert_threshold=body.alert_threshold,
        notes=body.notes,
    )
    if entry is None:
        raise HTTPException(409, f"Provider {body.npi} is already on the watchlist")
    return _enrich_with_scan_data(entry)


@router.delete("/{npi}")
async def remove_provider(npi: str):
    """Remove a provider from the watchlist."""
    if not remove_from_watchlist(npi):
        raise HTTPException(404, f"Provider {npi} not found on watchlist")
    return {"deleted": True}


@router.patch("/{npi}")
async def patch_provider(npi: str, body: UpdateWatchlistBody):
    """Update notes, threshold, active status, or reason for a watchlist entry."""
    updates = body.model_dump(exclude_unset=True)
    updated = update_entry(npi, **updates)
    if updated is None:
        raise HTTPException(404, f"Provider {npi} not found on watchlist")
    return _enrich_with_scan_data(updated)


@router.get("/alerts")
async def watchlist_alerts():
    """Get providers whose current risk score exceeds their alert threshold."""
    items = get_watchlist()
    enriched = [_enrich_with_scan_data(item) for item in items if item.get("active", True)]
    alerts = [e for e in enriched if e.get("in_alert")]
    alerts.sort(key=lambda x: (x.get("risk_score") or 0), reverse=True)
    return {"alerts": alerts, "total": len(alerts)}


@router.get("/check/{npi}")
async def check_watched(npi: str):
    """Check if a provider is on the watchlist."""
    return {"npi": npi, "watched": is_watched(npi)}
