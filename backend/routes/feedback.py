"""
Feedback loop API routes — exposes false positive/true positive tracking data.
"""
from fastapi import APIRouter, Depends
from routes.auth import require_user
from services.feedback_tracker import get_feedback_summary

router = APIRouter(prefix="/api/feedback", tags=["feedback"], dependencies=[Depends(require_user)])


@router.get("/summary")
async def feedback_summary():
    """Return signal-level FP/TP stats and current weight adjustments."""
    return get_feedback_summary()
