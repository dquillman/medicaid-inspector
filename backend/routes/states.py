from fastapi import APIRouter, Depends
from core.config import settings
from core.store import get_prescanned
from routes.auth import require_user

router = APIRouter(prefix="/api/states", tags=["states"], dependencies=[Depends(require_user)])


@router.get("/heatmap")
async def state_heatmap():
    """
    Per-state aggregates derived entirely from the prescan slim cache.
    No DuckDB/Parquet query needed — fast response from in-memory data.
    """
    prescanned: list[dict] = get_prescanned()

    state_map: dict[str, dict] = {}
    total_providers = 0
    total_paid = 0.0
    total_claims = 0
    total_beneficiaries = 0

    for p in prescanned:
        # slim cache stores state at top level; full cache may also have it in nppes.address
        state = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state", "")
        tp = p.get("total_paid", 0) or 0
        tc = p.get("total_claims", 0) or 0
        tb = p.get("total_beneficiaries", 0) or 0

        total_providers += 1
        total_paid += tp
        total_claims += tc
        total_beneficiaries += tb

        if not state:
            continue
        if state not in state_map:
            state_map[state] = {"state": state, "provider_count": 0, "total_paid": 0.0, "flagged_count": 0}
        state_map[state]["provider_count"] += 1
        state_map[state]["total_paid"] += tp
        if p.get("risk_score", 0) > settings.RISK_THRESHOLD:
            state_map[state]["flagged_count"] += 1

    return {
        "summary": {
            "total_providers": total_providers,
            "total_paid": total_paid,
            "total_claims": total_claims,
            "total_beneficiaries": total_beneficiaries,
        },
        "by_state": list(state_map.values()),
    }
