"""
Utilization analysis routes — expected vs actual utilization comparison.
"""
import re as _re
from fastapi import APIRouter, Depends, HTTPException, Query
from routes.auth import require_user
from services.utilization_analyzer import (
    analyze_by_state,
    analyze_outlier_providers,
    analyze_state_providers,
)

router = APIRouter(prefix="/api/utilization", tags=["utilization"], dependencies=[Depends(require_user)])


def _validate_state(state: str) -> str:
    """Validate state is a 2-letter code."""
    st = state.strip().upper()
    if not _re.match(r'^[A-Z]{2}$', st):
        raise HTTPException(400, f"Invalid state code '{state}'")
    return st


@router.get("/by-state")
async def utilization_by_state():
    """State-level utilization analysis with flagging."""
    states = analyze_by_state()
    flagged_count = sum(1 for s in states if s["flagged"])
    return {
        "states": states,
        "total_states": len(states),
        "flagged_states": flagged_count,
    }


@router.get("/outliers")
async def utilization_outliers(limit: int = Query(50, ge=1, le=500)):
    """Top providers whose utilization far exceeds expected (>3x state specialty avg)."""
    outliers = analyze_outlier_providers(limit=limit)
    return {
        "outliers": outliers,
        "total": len(outliers),
        "limit": limit,
    }


@router.get("/state/{state}")
async def utilization_state_detail(state: str):
    """Provider-level utilization breakdown within a state."""
    state = _validate_state(state)
    providers = analyze_state_providers(state)
    return {
        "state": state,
        "providers": providers,
        "total": len(providers),
    }
