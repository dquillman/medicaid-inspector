"""Fraud Ring Detection endpoints."""
from fastapi import APIRouter, HTTPException, Depends

from services.ring_detector import detect_rings, get_cached_rings, get_ring_by_id
from routes.auth import require_admin

router = APIRouter(prefix="/api/rings", tags=["rings"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_rings():
    """Return detected fraud rings (summary view)."""
    rings = get_cached_rings()
    if rings is None:
        return {"rings": [], "total": 0, "detected": False}

    # Return summary (without full edges/members detail for list view)
    summaries = []
    for r in rings:
        summaries.append({
            "ring_id": r["ring_id"],
            "member_count": r["member_count"],
            "total_paid": r["total_paid"],
            "avg_risk_score": r["avg_risk_score"],
            "high_risk_count": r["high_risk_count"],
            "total_flags": r["total_flags"],
            "density": r["density"],
            "suspicion_score": r["suspicion_score"],
            "connection_types": r["connection_types"],
        })

    return {"rings": summaries, "total": len(summaries), "detected": True}


@router.get("/{ring_id}")
async def get_ring_detail(ring_id: str):
    """Return full detail for a specific ring."""
    ring = get_ring_by_id(ring_id)
    if ring is None:
        raise HTTPException(status_code=404, detail="Ring not found. Run detection first.")
    return ring


@router.post("/detect")
async def trigger_detection():
    """Trigger fraud ring detection analysis."""
    rings = await detect_rings()
    return {
        "status": "complete",
        "rings_found": len(rings),
        "total_providers_in_rings": sum(r["member_count"] for r in rings),
    }
