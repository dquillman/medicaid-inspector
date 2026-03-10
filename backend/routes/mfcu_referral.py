"""
MFCU Referral workflow API routes.
Submit, track, and update referrals to Medicaid Fraud Control Units.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from core.referral_workflow import (
    create_referral,
    update_referral,
    get_referrals,
    get_referral_by_id,
    get_referral_by_npi,
    get_referral_stats,
    REFERRAL_STAGES,
    VALID_OUTCOMES,
)
from core.store import get_prescanned
from core.audit_log import log_action
from core.phi_logger import log_phi_access
from routes.auth import require_user

router = APIRouter(prefix="/api/referrals", tags=["referrals"], dependencies=[Depends(require_user)])


def _enrich_referral(ref: dict) -> dict:
    """Attach provider_name and state from prescan cache."""
    by_npi = {p["npi"]: p for p in get_prescanned()}
    p = by_npi.get(ref["npi"], {})
    name = p.get("provider_name") or (p.get("nppes") or {}).get("name") or ""
    state = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state") or ""
    risk_score = p.get("risk_score", 0)
    return {**ref, "provider_name": name, "state": state, "risk_score": risk_score}


# ── Submit referral ──────────────────────────────────────────────────────────

class SubmitReferralBody(BaseModel):
    mfcu_contact: str = ""
    jurisdiction: str = ""
    case_number: str = ""
    notes: str = ""


@router.post("/{npi}/submit")
async def submit_referral(
    npi: str,
    body: SubmitReferralBody,
    request: Request,
    user: dict = Depends(require_user),
):
    """Create a new MFCU referral for a provider."""
    username = user.get("username", "unknown")

    ref = create_referral(
        npi=npi,
        submitted_by=username,
        mfcu_contact=body.mfcu_contact,
        jurisdiction=body.jurisdiction,
        case_number=body.case_number,
        notes=body.notes,
    )

    # Audit log
    log_action(
        action_type="referral_submitted",
        entity_type="provider",
        entity_id=npi,
        details={"referral_id": ref["referral_id"], "jurisdiction": body.jurisdiction},
        user=username,
        ip_address=request.client.host if request.client else None,
    )

    # PHI access log
    log_phi_access(
        user_id=username,
        action="referral_submitted",
        resource_type="referral",
        resource_id=npi,
        ip_address=request.client.host if request.client else None,
    )

    return _enrich_referral(ref)


# ── List all referrals ───────────────────────────────────────────────────────

@router.get("")
async def list_referrals(stage: Optional[str] = None, npi: Optional[str] = None):
    """List all referrals, optionally filtered by stage or NPI."""
    items = get_referrals(stage_filter=stage, npi_filter=npi)
    enriched = [_enrich_referral(r) for r in items]
    return {"referrals": enriched, "total": len(enriched)}


# ── Get referral by ID ───────────────────────────────────────────────────────

@router.get("/{referral_id:int}")
async def get_referral(referral_id: int):
    """Get a single referral by numeric ID."""
    ref = get_referral_by_id(referral_id)
    if not ref:
        raise HTTPException(404, f"Referral {referral_id} not found")
    return _enrich_referral(ref)


# ── Get referrals for a provider ─────────────────────────────────────────────

@router.get("/provider/{npi}")
async def get_provider_referrals(npi: str):
    """Get all referrals for a specific provider NPI."""
    items = get_referral_by_npi(npi)
    enriched = [_enrich_referral(r) for r in items]
    return {"npi": npi, "referrals": enriched, "total": len(enriched)}


# ── Update referral ──────────────────────────────────────────────────────────

class UpdateReferralBody(BaseModel):
    stage: Optional[str] = None
    outcome: Optional[str] = None
    outcome_notes: Optional[str] = None
    mfcu_contact: Optional[str] = None
    case_number: Optional[str] = None
    jurisdiction: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/{referral_id:int}")
async def update_referral_endpoint(
    referral_id: int,
    body: UpdateReferralBody,
    request: Request,
    user: dict = Depends(require_user),
):
    """Update a referral's stage, outcome, or metadata."""
    username = user.get("username", "unknown")

    try:
        ref = update_referral(
            referral_id=referral_id,
            stage=body.stage,
            outcome=body.outcome,
            outcome_notes=body.outcome_notes,
            mfcu_contact=body.mfcu_contact,
            case_number=body.case_number,
            jurisdiction=body.jurisdiction,
            notes=body.notes,
            updated_by=username,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if ref is None:
        raise HTTPException(404, f"Referral {referral_id} not found")

    # Audit log
    details: dict = {"referral_id": ref["referral_id"]}
    if body.stage:
        details["new_stage"] = body.stage
    if body.outcome:
        details["outcome"] = body.outcome
    log_action(
        action_type="referral_updated",
        entity_type="provider",
        entity_id=ref["npi"],
        details=details,
        user=username,
        ip_address=request.client.host if request.client else None,
    )

    return _enrich_referral(ref)


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def referral_stats():
    """Aggregate referral statistics."""
    return get_referral_stats()


# ── Reference data ────────────────────────────────────────────────────────────

@router.get("/meta/stages")
async def referral_stages():
    """Return valid referral stages."""
    return {"stages": REFERRAL_STAGES}


@router.get("/meta/outcomes")
async def referral_outcomes():
    """Return valid referral outcomes."""
    return {"outcomes": VALID_OUTCOMES}
