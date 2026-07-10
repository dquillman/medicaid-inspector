"""
Claim-level fraud pattern detection API routes.
"""
import re as _re

from fastapi import APIRouter, Depends, HTTPException, Query
from routes.auth import require_user

router = APIRouter(prefix="/api/claim-patterns", tags=["claim-patterns"], dependencies=[Depends(require_user)])


def _validate_npi(npi: str) -> str:
    """Validate NPI is exactly 10 digits."""
    npi = npi.strip()
    if not _re.match(r'^\d{10}$', npi):
        raise HTTPException(400, f"Invalid NPI '{npi}' — must be exactly 10 digits")
    return npi


def _stamp_risk(patterns: list) -> list:
    """Attach the provider's composite risk_score to each pattern row (Brain-flag
    parity, #2): lets the Claim Patterns page show the same high-risk indicator
    the other analysis pages use, at the same threatBand thresholds. Cache
    lookup only — never recomputes anything."""
    from core.store import get_provider_by_npi
    for p in patterns:
        if isinstance(p, dict) and p.get("npi") and "risk_score" not in p:
            prov = get_provider_by_npi(p["npi"]) or {}
            p["risk_score"] = round(float(prov.get("risk_score") or 0), 1)
    return patterns


@router.get("/all")
async def claim_patterns_all(limit: int = Query(100, ge=1, le=500)):
    """Return all 5 pattern analyses in a single response."""
    from services.claim_patterns import _run_all_analyses
    result = await _run_all_analyses(limit=limit)
    # Stamp risk_score on each pattern list in the combined payload.
    for key, val in result.items():
        if isinstance(val, list):
            _stamp_risk(val)
        elif isinstance(val, dict) and isinstance(val.get("patterns"), list):
            _stamp_risk(val["patterns"])
    return result


@router.get("/summary")
async def claim_patterns_summary():
    """Counts of each pattern type detected across all providers."""
    from services.claim_patterns import get_summary
    return await get_summary()


@router.get("/unbundling")
async def unbundling_patterns(limit: int = Query(100, ge=1, le=500)):
    """Providers with unbundling indicators — billing components instead of bundled codes."""
    from services.claim_patterns import detect_unbundling
    results = _stamp_risk(await detect_unbundling(limit=limit))
    return {"patterns": results, "total": len(results)}


@router.get("/duplicates")
async def duplicate_patterns(limit: int = Query(100, ge=1, le=500)):
    """Duplicate claim clusters — identical or near-identical claims."""
    from services.claim_patterns import detect_duplicates
    results = _stamp_risk(await detect_duplicates(limit=limit))
    return {"patterns": results, "total": len(results)}


@router.get("/place-of-service")
async def pos_violation_patterns(limit: int = Query(100, ge=1, le=500)):
    """Place-of-service violations — procedure/setting mismatches."""
    from services.claim_patterns import detect_pos_violations
    results = _stamp_risk(await detect_pos_violations(limit=limit))
    return {"patterns": results, "total": len(results)}


@router.get("/modifiers")
async def modifier_abuse_patterns(limit: int = Query(100, ge=1, le=500)):
    """Modifier abuse cases — unusual modifier usage rates."""
    from services.claim_patterns import detect_modifier_abuse
    results = _stamp_risk(await detect_modifier_abuse(limit=limit))
    return {"patterns": results, "total": len(results)}


@router.get("/impossible-days")
async def impossible_day_patterns(limit: int = Query(100, ge=1, le=500)):
    """Same-day impossible patterns — physically impossible billing volumes."""
    from services.claim_patterns import detect_impossible_days
    results = _stamp_risk(await detect_impossible_days(limit=limit))
    return {"patterns": results, "total": len(results)}


@router.get("/provider/{npi}")
async def provider_claim_patterns(npi: str):
    """All claim-level patterns for a single provider."""
    npi = _validate_npi(npi)
    from services.claim_patterns import get_provider_claim_patterns
    return await get_provider_claim_patterns(npi)
