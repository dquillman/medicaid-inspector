"""
Population ratio analysis routes.

GET /api/population/ratios        — State-level provider-to-population ratios
GET /api/population/overcapacity  — Providers billing beyond physical capacity
GET /api/population/state/{state}/zips — ZIP-level breakdown within a state
"""

from fastapi import APIRouter, Depends
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
async def overcapacity_providers():
    """Providers billing beyond estimated physical capacity."""
    results = compute_billing_capacity()
    return {"providers": results, "total": len(results)}


@router.get("/state/{state}/zips")
async def state_zip_breakdown(state: str):
    """ZIP-prefix-level provider density breakdown within a state."""
    return compute_zip_ratios(state)
