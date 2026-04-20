"""
Hotspot API routes — county/ZIP3-level fraud heatmap endpoints.
"""

from fastapi import APIRouter, HTTPException, Depends
from services.hotspot_engine import compute_hotspots, get_hotspot_detail
from routes.auth import require_user

router = APIRouter(prefix="/api/hotspots", tags=["hotspots"], dependencies=[Depends(require_user)])


@router.get("/composite")
async def composite_hotspots():
    """All ZIP3 areas ranked by composite score, with component breakdown."""
    hotspots = compute_hotspots()
    severity_counts = {
        "CRITICAL": sum(1 for h in hotspots if h["severity"] == "CRITICAL"),
        "HIGH":     sum(1 for h in hotspots if h["severity"] == "HIGH"),
        "ELEVATED": sum(1 for h in hotspots if h["severity"] == "ELEVATED"),
        "NORMAL":   sum(1 for h in hotspots if h["severity"] == "NORMAL"),
    }
    return {
        "total_areas":     len(hotspots),
        "severity_counts": severity_counts,
        "hotspots":        hotspots,
    }


@router.get("/top")
async def top_hotspots(limit: int = 20):
    """Top N hotspots with full detail including provider lists."""
    hotspots = compute_hotspots()
    top = hotspots[:limit]
    # Enrich each with provider detail
    enriched = []
    for h in top:
        detail = get_hotspot_detail(h["zip3"])
        if detail:
            enriched.append(detail)
        else:
            enriched.append(h)
    return {
        "total_areas": len(hotspots),
        "hotspots":    enriched,
    }


@router.get("/zip/{zip3}")
async def zip3_detail(zip3: str):
    """Drill into a specific ZIP3 area with component breakdown and provider list."""
    detail = get_hotspot_detail(zip3)
    if not detail:
        raise HTTPException(404, f"No data for ZIP3 area {zip3}")
    return detail
