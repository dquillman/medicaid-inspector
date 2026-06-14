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
async def add_tip(body: AddTipBody):
    if not (body.npi or "").strip():
        raise HTTPException(400, "npi is required")
    return oig_tips_store.add_tip(
        npi=body.npi.strip(), provider_name=body.provider_name,
        state=body.state, risk_score=body.risk_score, notes=body.notes,
    )


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
