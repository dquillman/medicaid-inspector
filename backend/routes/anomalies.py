from fastapi import APIRouter, Query
from core.config import settings
from core.store import get_prescanned

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])

VALID_SIGNALS = {
    "billing_concentration",
    "revenue_per_bene_outlier",
    "claims_per_bene_anomaly",
    "billing_ramp_rate",
    "bust_out_pattern",
    "ghost_billing",
    "total_spend_outlier",
    "billing_consistency",
    "bene_concentration",
    "upcoding_pattern",
    "address_cluster_risk",
    "oig_excluded",
    "specialty_mismatch",
    "corporate_shell_risk",
    "dead_npi_billing",
    "new_provider_explosion",
    "geographic_impossibility",
}


@router.get("")
async def list_anomalies(
    signal: str = Query("", description="Filter by specific fraud signal name"),
    state: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Returns providers with risk_score > RISK_THRESHOLD, grouped by fraud signal.
    Uses the pre-scanned cache populated at startup.
    """
    prescanned: list[dict] = get_prescanned()

    filtered = [p for p in prescanned if p["risk_score"] > settings.RISK_THRESHOLD]

    if signal and signal in VALID_SIGNALS:
        filtered = [
            p for p in filtered
            if any(f["signal"] == signal for f in p.get("flags", []))
        ]

    # Always sort highest risk first
    filtered.sort(key=lambda p: p.get("risk_score", 0), reverse=True)

    total = len(filtered)
    start = (page - 1) * limit
    page_data = filtered[start: start + limit]

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "anomalies": page_data,
    }


@router.get("/signals/summary")
async def signal_summary():
    """Count of flagged providers per signal type (for bar chart)."""
    prescanned: list[dict] = get_prescanned()
    flagged = [p for p in prescanned if p["risk_score"] > settings.RISK_THRESHOLD]

    counts: dict[str, int] = {s: 0 for s in VALID_SIGNALS}
    for provider in flagged:
        for flag in provider.get("flags", []):
            sig = flag["signal"]
            if sig in counts:
                counts[sig] += 1

    return [{"signal": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
