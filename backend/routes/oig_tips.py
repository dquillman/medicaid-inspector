"""HHS-OIG Hotline tip log API."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routes.auth import require_user
from core import oig_tips_store

router = APIRouter(prefix="/api/oig-tips", tags=["oig-tips"], dependencies=[Depends(require_user)])


class AddTipBody(BaseModel):
    npi: str
    provider_name: str = ""
    state: str = ""
    risk_score: float = 0.0
    notes: str = ""


class UpdateTipBody(BaseModel):
    status: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    outcome_notes: str | None = None


@router.get("")
async def list_tips():
    return {"tips": oig_tips_store.list_tips(), "counts": oig_tips_store.counts()}


@router.get("/filed")
async def filed():
    """Lightweight NPI set for cross-page 'tip filed' badges."""
    return {"npis": sorted(oig_tips_store.filed_npis())}


@router.post("")
async def add_tip(body: AddTipBody, user: dict = Depends(require_user)):
    if not (body.npi or "").strip():
        raise HTTPException(400, "npi is required")
    npi = body.npi.strip()
    tip = oig_tips_store.add_tip(
        npi=npi, provider_name=body.provider_name,
        state=body.state, risk_score=body.risk_score, notes=body.notes,
    )
    # Single source of truth, mirroring mfcu_referral.py's /submit: logging an
    # OIG tip IS the case reaching "Reported: OIG". Before this, nothing in the
    # codebase ever set queue_status to tip_filed — a human had to separately
    # remember to flip it from the Review Queue, and the two could drift.
    # Best-effort — the provider may not be in the review queue.
    try:
        from core.review_store import set_queue_status
        set_queue_status(npi, "tip_filed", actor=user.get("username", "unknown"),
                          actor_type="user", note="HHS-OIG Hotline tip logged as filed")
    except Exception:
        pass
    return tip


@router.patch("/{tip_id}")
async def update_tip(tip_id: str, body: UpdateTipBody):
    try:
        updated = oig_tips_store.update_tip(
            tip_id, status=body.status, reference_number=body.reference_number,
            notes=body.notes, outcome_notes=body.outcome_notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(404, f"Tip not found: {tip_id}")
    return updated
