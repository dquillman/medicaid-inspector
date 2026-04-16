"""
ROI tracking API routes.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from core.roi_store import (
    add_recovery,
    get_recoveries,
    get_roi_summary,
    delete_recovery,
)

from routes.auth import require_admin

router = APIRouter(prefix="/api/roi", tags=["roi"], dependencies=[Depends(require_admin)])


class RecoveryBody(BaseModel):
    npi: str
    amount: float
    recovery_type: str
    notes: str = ""


@router.get("/summary")
async def roi_summary():
    """ROI dashboard data — KPIs, monthly trends, top recoveries."""
    return get_roi_summary()


@router.post("/recovery")
async def log_recovery(body: RecoveryBody):
    """Log a new recovery entry."""
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    if body.recovery_type not in {"overpayment", "settlement", "penalty", "voluntary_refund"}:
        raise HTTPException(400, f"Invalid recovery_type: {body.recovery_type}")
    record = add_recovery(body.npi, body.amount, body.recovery_type, body.notes)
    return record


@router.get("/recoveries")
async def list_recoveries(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """List all recoveries, paginated."""
    return get_recoveries(page=page, limit=limit)


@router.delete("/recovery/{recovery_id}")
async def remove_recovery(recovery_id: str):
    """Remove a recovery entry by ID."""
    removed = delete_recovery(recovery_id)
    if not removed:
        raise HTTPException(404, f"Recovery not found: {recovery_id}")
    return {"deleted": True, "id": recovery_id}
