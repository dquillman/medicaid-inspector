"""
Integration routes — MMIS, NPPES bulk, DEA, Email, FHIR.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from routes.auth import require_user

router = APIRouter(prefix="/api/integrations", tags=["integrations"], dependencies=[Depends(require_user)])
admin_router = APIRouter(prefix="/api/admin", tags=["admin-integrations"], dependencies=[Depends(require_user)])
provider_router = APIRouter(prefix="/api/providers", tags=["provider-integrations"], dependencies=[Depends(require_user)])


# ── MMIS ──────────────────────────────────────────────────────────────────────

@router.get("/mmis/status")
async def mmis_status():
    """Return MMIS connection/configuration status."""
    from services.mmis_client import get_mmis_client
    client = get_mmis_client()
    return await client.get_status()


@router.get("/mmis/eligibility/{bene_id}")
async def mmis_eligibility(bene_id: str):
    """Check beneficiary eligibility via MMIS (stub)."""
    from services.mmis_client import get_mmis_client
    client = get_mmis_client()
    return await client.check_eligibility(bene_id)


@router.get("/mmis/enrollment/{npi}")
async def mmis_enrollment(npi: str):
    """Check provider enrollment status via MMIS (stub)."""
    from services.mmis_client import get_mmis_client
    client = get_mmis_client()
    return await client.get_enrollment(npi)


# ── NPPES Bulk ────────────────────────────────────────────────────────────────

@admin_router.post("/nppes-bulk-refresh")
async def nppes_bulk_refresh():
    """Trigger download of NPPES bulk data."""
    from services.nppes_bulk import refresh_bulk_data
    return await refresh_bulk_data()


@admin_router.get("/nppes-bulk-status")
async def nppes_bulk_status():
    """Return NPPES bulk cache status."""
    from services.nppes_bulk import get_bulk_status
    return get_bulk_status()


# ── DEA ───────────────────────────────────────────────────────────────────────

@provider_router.get("/{npi}/dea")
async def provider_dea(npi: str):
    """Return DEA registration status for a provider."""
    from services.dea_lookup import lookup_dea_by_npi
    return await lookup_dea_by_npi(npi)


# ── Email/SMTP ────────────────────────────────────────────────────────────────

class TestEmailRequest(BaseModel):
    to: str

@admin_router.post("/email/test")
async def email_test(body: TestEmailRequest):
    """Send a test email to verify SMTP configuration."""
    from services.email_service import send_email
    result = await send_email(
        to=body.to,
        subject="[Medicaid Inspector] Test Email",
        body_html="""
        <html><body style="font-family:sans-serif;">
        <h2>Test Email</h2>
        <p>This is a test email from <strong>Medicaid Fraud Inspector</strong>.</p>
        <p>If you received this, your SMTP configuration is working correctly.</p>
        </body></html>
        """,
    )
    return result


@admin_router.get("/email/status")
async def email_status():
    """Return SMTP configuration status."""
    from services.email_service import get_smtp_status
    return get_smtp_status()


# ── FHIR ──────────────────────────────────────────────────────────────────────

@provider_router.get("/{npi}/fhir")
async def provider_fhir(npi: str):
    """Return provider data as FHIR R4 Practitioner JSON."""
    from core.store import get_prescanned
    from data.nppes_client import get_provider
    from services.fhir_exporter import provider_to_fhir_practitioner

    # Get scoring data from prescan cache
    scoring = {}
    for p in get_prescanned():
        if p.get("npi") == npi:
            scoring = p
            break

    # Get NPPES data
    nppes_data = {}
    try:
        nppes_data = await get_provider(npi)
    except Exception:
        pass

    if not nppes_data and not scoring:
        raise HTTPException(status_code=404, detail=f"Provider {npi} not found")

    return provider_to_fhir_practitioner(npi, nppes_data or {}, scoring)


@provider_router.get("/{npi}/fhir/report")
async def provider_fhir_report(npi: str):
    """Return investigation findings as FHIR R4 DocumentReference JSON."""
    from core.store import get_prescanned
    from data.nppes_client import get_provider
    from services.fhir_exporter import investigation_to_fhir_document_reference

    # Get scoring data from prescan cache
    scoring = {}
    for p in get_prescanned():
        if p.get("npi") == npi:
            scoring = p
            break

    if not scoring:
        raise HTTPException(status_code=404, detail=f"Provider {npi} not found in scan results")

    # Get NPPES data
    nppes_data = {}
    try:
        nppes_data = await get_provider(npi)
    except Exception:
        pass

    flags = scoring.get("signal_results", scoring.get("flags", []))
    return investigation_to_fhir_document_reference(npi, nppes_data or {}, scoring, flags)
