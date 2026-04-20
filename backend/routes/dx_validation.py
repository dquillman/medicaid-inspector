"""
Diagnosis-to-Procedure validation API routes.
Validates billed codes against provider specialty using CMS crosswalk data.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_user
from services.dx_procedure_validator import validate_provider_codes, batch_validate_codes

router = APIRouter(prefix="/api/dx-validation", tags=["dx-validation"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


@router.get("/provider/{npi}")
async def validate_provider(npi: str):
    """Validate a provider's billed codes against their specialty."""
    try:
        result = await validate_provider_codes(npi)
        if not result.get("found"):
            raise HTTPException(404, result.get("error", "Provider not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("DX validation failed for %s: %s", npi, e)
        raise HTTPException(500, str(e))


@router.get("/batch")
async def batch_validate(limit: int = 100, min_mismatch_pct: float = 30.0):
    """
    Validate all providers' codes against their specialties.
    Returns providers with mismatch_score above the threshold (default 30%).
    """
    try:
        return await batch_validate_codes(limit=limit, min_mismatch_pct=min_mismatch_pct)
    except Exception as e:
        log.error("Batch DX validation failed: %s", e)
        raise HTTPException(500, str(e))
