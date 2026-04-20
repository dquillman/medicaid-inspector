"""
Prescription/Rx anomaly detection API routes.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_user
from services.rx_anomaly_detector import detect_rx_anomalies, provider_rx_profile

router = APIRouter(prefix="/api/rx-anomalies", tags=["rx-anomalies"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


@router.get("")
async def list_rx_anomalies(limit: int = 100):
    """Find providers with suspicious prescription/drug billing patterns."""
    try:
        return await detect_rx_anomalies(limit=limit)
    except Exception as e:
        log.error("Rx anomaly detection failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/provider/{npi}")
async def get_provider_rx_profile(npi: str):
    """Detailed Rx billing profile for a specific provider."""
    try:
        result = await provider_rx_profile(npi)
        if not result.get("found"):
            raise HTTPException(404, result.get("error", "Provider not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("Rx profile failed for %s: %s", npi, e)
        raise HTTPException(500, str(e))
