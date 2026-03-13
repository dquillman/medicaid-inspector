"""
Claim-level fraud pattern detection API routes.
"""

from fastapi import APIRouter, Depends
from routes.auth import require_user

router = APIRouter(prefix="/api/claim-patterns", tags=["claim-patterns"], dependencies=[Depends(require_user)])


@router.get("/all")
async def claim_patterns_all(limit: int = 100):
    """Return all 5 pattern analyses in a single response."""
    from services.claim_patterns import _run_all_analyses
    return await _run_all_analyses(limit=limit)


@router.get("/summary")
async def claim_patterns_summary():
    """Counts of each pattern type detected across all providers."""
    from services.claim_patterns import get_summary
    return await get_summary()


@router.get("/unbundling")
async def unbundling_patterns(limit: int = 100):
    """Providers with unbundling indicators — billing components instead of bundled codes."""
    from services.claim_patterns import detect_unbundling
    results = await detect_unbundling(limit=limit)
    return {"patterns": results, "total": len(results)}


@router.get("/duplicates")
async def duplicate_patterns(limit: int = 100):
    """Duplicate claim clusters — identical or near-identical claims."""
    from services.claim_patterns import detect_duplicates
    results = await detect_duplicates(limit=limit)
    return {"patterns": results, "total": len(results)}


@router.get("/place-of-service")
async def pos_violation_patterns(limit: int = 100):
    """Place-of-service violations — procedure/setting mismatches."""
    from services.claim_patterns import detect_pos_violations
    results = await detect_pos_violations(limit=limit)
    return {"patterns": results, "total": len(results)}


@router.get("/modifiers")
async def modifier_abuse_patterns(limit: int = 100):
    """Modifier abuse cases — unusual modifier usage rates."""
    from services.claim_patterns import detect_modifier_abuse
    results = await detect_modifier_abuse(limit=limit)
    return {"patterns": results, "total": len(results)}


@router.get("/impossible-days")
async def impossible_day_patterns(limit: int = 100):
    """Same-day impossible patterns — physically impossible billing volumes."""
    from services.claim_patterns import detect_impossible_days
    results = await detect_impossible_days(limit=limit)
    return {"patterns": results, "total": len(results)}


@router.get("/provider/{npi}")
async def provider_claim_patterns(npi: str):
    """All claim-level patterns for a single provider."""
    from services.claim_patterns import get_provider_claim_patterns
    return await get_provider_claim_patterns(npi)
