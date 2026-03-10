"""
Beneficiary-level fraud detection endpoints.
Surfaces provider patterns that indicate beneficiary-side fraud:
doctor shopping, high utilization, geographic impossibility, excessive services.
"""
import logging

from fastapi import APIRouter, HTTPException, Depends

from routes.auth import require_user
from services.beneficiary_analyzer import (
    beneficiary_fraud_summary,
    detect_doctor_shopping,
    detect_high_utilization,
    detect_geographic_anomalies,
    detect_excessive_services,
    provider_beneficiary_fraud,
)

router = APIRouter(prefix="/api/beneficiary-fraud", tags=["beneficiary-fraud"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


@router.get("/summary")
async def get_summary():
    """Overview stats: total beneficiaries analyzed, flagged count by type."""
    try:
        return await beneficiary_fraud_summary()
    except Exception as e:
        log.error("Beneficiary fraud summary failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/doctor-shopping")
async def get_doctor_shopping(limit: int = 100):
    """Beneficiaries/providers with doctor-shopping patterns."""
    try:
        return await detect_doctor_shopping(limit=limit)
    except Exception as e:
        log.error("Doctor shopping endpoint failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/high-utilization")
async def get_high_utilization(limit: int = 100):
    """Providers with abnormally high beneficiary utilization."""
    try:
        return await detect_high_utilization(limit=limit)
    except Exception as e:
        log.error("High utilization endpoint failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/geographic-anomalies")
async def get_geographic_anomalies(limit: int = 100):
    """Providers with geographic impossibility patterns."""
    try:
        return await detect_geographic_anomalies(limit=limit)
    except Exception as e:
        log.error("Geographic anomalies endpoint failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/excessive-services")
async def get_excessive_services(limit: int = 100):
    """Providers with excessive services per beneficiary."""
    try:
        return await detect_excessive_services(limit=limit)
    except Exception as e:
        log.error("Excessive services endpoint failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/provider/{npi}")
async def get_provider_beneficiary_fraud(npi: str):
    """Beneficiary fraud patterns linked to a specific provider's patient panel."""
    try:
        result = await provider_beneficiary_fraud(npi)
        if not result.get("found") and not result.get("error"):
            raise HTTPException(status_code=404, detail=f"Provider {npi} not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("Provider beneficiary fraud failed for %s: %s", npi, e)
        raise HTTPException(status_code=500, detail=str(e))
