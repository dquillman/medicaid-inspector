from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_user

router = APIRouter(prefix="/api/license", tags=["license"], dependencies=[Depends(require_user)])


@router.get("/providers/{npi}")
async def provider_license(npi: str):
    """License and credential verification for a single provider."""
    from services.license_checker import verify_provider_credentials

    result = await verify_provider_credentials(npi)
    if not result.get("verified") and result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/flags")
async def license_flags():
    """System-wide list of providers with credential concerns."""
    from services.license_checker import scan_all_credential_flags

    return await scan_all_credential_flags()
