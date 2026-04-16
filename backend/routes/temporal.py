"""
Temporal anomaly detection routes — time-based billing pattern analysis.
"""
import logging
import re as _re
from fastapi import APIRouter, HTTPException, Depends

from services.temporal_analyzer import analyze_provider_temporal, get_system_temporal_patterns
from routes.auth import require_user

router = APIRouter(prefix="/api/temporal", tags=["temporal"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


def _validate_npi(npi: str) -> str:
    """Validate NPI is exactly 10 digits."""
    npi = npi.strip()
    if not _re.match(r'^\d{10}$', npi):
        raise HTTPException(400, f"Invalid NPI '{npi}' — must be exactly 10 digits")
    return npi


@router.get("/providers/{npi}")
async def provider_temporal_analysis(npi: str):
    """
    Full temporal analysis for a single provider.
    Returns day-of-week distribution, monthly trend with anomaly flags,
    detected anomalies, and impossible day volumes.
    """
    npi = _validate_npi(npi)
    try:
        result = await analyze_provider_temporal(npi)
    except Exception as e:
        log.error(f"Temporal analysis failed for {npi}: {e}")
        raise HTTPException(500, f"Temporal analysis failed: {e}")

    if result["summary"]["total_months"] == 0:
        raise HTTPException(404, f"No billing data found for NPI {npi}")

    return result


@router.get("/system-patterns")
async def system_patterns():
    """
    System-wide temporal patterns for baseline comparison.
    """
    try:
        return await get_system_temporal_patterns()
    except Exception as e:
        log.error(f"System temporal patterns failed: {e}")
        raise HTTPException(500, f"System temporal patterns failed: {e}")
