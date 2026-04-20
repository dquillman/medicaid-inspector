from fastapi import APIRouter, Depends
from data.duckdb_client import query_async, get_parquet_path
from core.config import settings
from core.store import get_prescanned
from routes.auth import require_user

router = APIRouter(prefix="/api/states", tags=["states"], dependencies=[Depends(require_user)])


@router.get("/heatmap")
async def state_heatmap():
    """
    Per-state aggregates: total_paid, provider_count.
    Flagged provider count is derived from the prescan cache.
    """
    summary_sql = f"""
    SELECT
        COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM) AS total_providers,
        SUM(TOTAL_PAID)                           AS total_paid,
        SUM(TOTAL_CLAIMS)                         AS total_claims,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)           AS total_beneficiaries
    FROM read_parquet('{get_parquet_path()}')
    """
    rows = await query_async(summary_sql)

    # State breakdown from prescan cache.
    # NPPES enricher stores state as a top-level field on each provider.
    prescanned: list[dict] = get_prescanned()

    state_map: dict[str, dict] = {}
    for p in prescanned:
        # Top-level "state" is set by the NPPES enricher; fall back to nppes.address.state
        state = p.get("state") or p.get("nppes", {}).get("address", {}).get("state", "")
        if not state:
            continue
        if state not in state_map:
            state_map[state] = {"state": state, "provider_count": 0, "total_paid": 0, "flagged_count": 0}
        state_map[state]["provider_count"] += 1
        state_map[state]["total_paid"] += p.get("total_paid", 0)
        if p.get("risk_score", 0) > settings.RISK_THRESHOLD:
            state_map[state]["flagged_count"] += 1

    return {
        "summary": rows[0] if rows else {},
        "by_state": list(state_map.values()),
    }
