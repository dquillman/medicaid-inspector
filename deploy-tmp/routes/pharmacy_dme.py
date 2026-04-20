"""
Pharmacy & DME fraud detection endpoints.

Provides high-risk provider lists and per-provider detail for both
pharmacy/drug fraud and DME fraud analysis.
"""
from fastapi import APIRouter, Query, Depends
from routes.auth import require_user

router = APIRouter(prefix="/api", tags=["pharmacy-dme"], dependencies=[Depends(require_user)])


# ── Pharmacy endpoints ──────────────────────────────────────────────────────

@router.get("/pharmacy/high-risk")
async def pharmacy_high_risk(limit: int = Query(50, ge=1, le=200)):
    """Providers with pharmacy fraud indicators, sorted by risk."""
    from services.pharmacy_analyzer import get_high_risk_providers
    return await get_high_risk_providers(limit=limit)


@router.get("/pharmacy/provider/{npi}")
async def pharmacy_provider(npi: str):
    """Pharmacy fraud analysis for a specific provider."""
    from services.pharmacy_analyzer import analyze_provider
    return await analyze_provider(npi)


# ── DME endpoints ────────────────────────────────────────────────────────────

@router.get("/dme/high-risk")
async def dme_high_risk(limit: int = Query(50, ge=1, le=200)):
    """Providers with DME fraud indicators, sorted by risk."""
    from services.dme_analyzer import get_high_risk_providers
    return await get_high_risk_providers(limit=limit)


@router.get("/dme/provider/{npi}")
async def dme_provider(npi: str):
    """DME fraud analysis for a specific provider."""
    from services.dme_analyzer import analyze_provider
    return await analyze_provider(npi)
