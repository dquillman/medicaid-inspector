"""
Trend divergence routes — enrollment vs billing growth analysis.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends

from services.trend_divergence import compute_trend_divergence, get_state_detail

from routes.auth import require_user

router = APIRouter(prefix="/api/trends", tags=["trends"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


@router.get("/divergence")
async def all_state_divergence():
    """
    All states with year-over-year enrollment vs billing trends and divergence flags.
    """
    trends = compute_trend_divergence()

    flagged_count = sum(1 for t in trends if t["flagged"])
    with_data = [t for t in trends if t["has_billing_data"]]

    largest_divergence_state = with_data[0]["state"] if with_data else None
    largest_divergence_score = with_data[0]["divergence_score"] if with_data else 0.0

    # Average billing-per-enrollee growth across all states with data
    avg_billing_growth = 0.0
    avg_enrollment_growth = 0.0
    count = 0
    for t in with_data:
        yoy_list = t.get("yoy", [])
        if yoy_list:
            avg_billing_growth += sum(y["billing_change_pct"] for y in yoy_list) / len(yoy_list)
            avg_enrollment_growth += sum(y["enrollment_change_pct"] for y in yoy_list) / len(yoy_list)
            count += 1
    if count > 0:
        avg_billing_growth = round(avg_billing_growth / count, 1)
        avg_enrollment_growth = round(avg_enrollment_growth / count, 1)

    return {
        "summary": {
            "total_states": len(trends),
            "states_with_data": len(with_data),
            "states_flagged": flagged_count,
            "largest_divergence_state": largest_divergence_state,
            "largest_divergence_score": largest_divergence_score,
            "avg_billing_growth_pct": avg_billing_growth,
            "avg_enrollment_growth_pct": avg_enrollment_growth,
        },
        "states": trends,
    }


@router.get("/state/{state}")
async def state_detail(state: str):
    """
    Detailed yearly breakdown for a single state.
    """
    detail = get_state_detail(state)
    if not detail:
        raise HTTPException(404, f"No data found for state '{state}'")
    return detail
