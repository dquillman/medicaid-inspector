"""
Population ratio analysis routes.

GET /api/population/ratios        — State-level provider-to-population ratios
GET /api/population/overcapacity  — Providers billing beyond physical capacity
GET /api/population/state/{state}/zips — ZIP-level breakdown within a state
"""

from fastapi import APIRouter, Depends, Query
from routes.auth import require_user

from services.population_ratio import (
    compute_provider_ratios,
    compute_billing_capacity,
    compute_zip_ratios,
)

router = APIRouter(prefix="/api/population", tags=["population"], dependencies=[Depends(require_user)])


@router.get("/ratios")
async def provider_ratios():
    """State-level provider-to-Medicaid-population ratios."""
    return compute_provider_ratios()


@router.get("/overcapacity")
async def overcapacity_providers(limit: int = Query(200, ge=1, le=5000)):
    """Providers billing beyond estimated physical capacity.

    Default limit of 200 keeps response payload small (~50 KB) — the full
    list contains ~250k providers (25 MB JSON). The UI only renders the
    top-N so trimming server-side avoids a 25 MB transfer per page load.
    """
    results = compute_billing_capacity()  # service-level cache returns instantly
    total = len(results)
    return {"providers": results[:limit], "total": total, "limit": limit}


@router.get("/state/{state}/zips")
async def state_zip_breakdown(state: str):
    """ZIP-prefix-level provider density breakdown within a state."""
    return compute_zip_ratios(state)
