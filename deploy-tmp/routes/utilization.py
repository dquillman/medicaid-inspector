"""
Utilization analysis routes — expected vs actual utilization comparison.
"""
from fastapi import APIRouter, Depends
from routes.auth import require_user
from services.utilization_analyzer import (
    analyze_by_state,
    analyze_outlier_providers,
    analyze_state_providers,
)

router = APIRouter(prefix="/api/utilization", tags=["utilization"], dependencies=[Depends(require_user)])


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
async def utilization_outliers(limit: int = 50):
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
    providers = analyze_state_providers(state)
    return {
        "state": state.upper(),
        "providers": providers,
        "total": len(providers),
    }
