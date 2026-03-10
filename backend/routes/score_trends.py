"""
Risk Score Trend Tracking API endpoints.
"""
from fastapi import APIRouter, Depends

from core.score_history import get_history, get_movers, get_summary
from core.store import get_prescanned
from routes.auth import require_user

router = APIRouter(prefix="/api/score-trends", tags=["score-trends"], dependencies=[Depends(require_user)])


@router.get("/movers/list")
async def score_movers(top: int = 10):
    """Providers with the biggest risk score changes between scans."""
    movers = get_movers(top_n=top)

    # Enrich with provider names
    name_map: dict[str, str] = {}
    for p in get_prescanned():
        npi = p.get("npi")
        if npi:
            name_map[npi] = p.get("provider_name") or p.get("nppes", {}).get("name") or ""

    for lst in [movers["rising"], movers["falling"]]:
        for m in lst:
            m["provider_name"] = name_map.get(m["npi"], "")

    return movers


@router.get("/summary/distribution")
async def score_summary():
    """System-wide score distribution over time."""
    return get_summary()


@router.get("/{npi}")
async def provider_score_trend(npi: str):
    """Risk score history for a single provider."""
    history = get_history(npi)

    # Enrich with provider name from prescan cache
    provider_name = None
    for p in get_prescanned():
        if p.get("npi") == npi:
            provider_name = p.get("provider_name") or p.get("nppes", {}).get("name")
            break

    return {
        "npi": npi,
        "provider_name": provider_name,
        "snapshots": history,
        "snapshot_count": len(history),
    }
