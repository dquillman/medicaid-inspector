"""
Provider Timeline Analysis — enhanced monthly billing timeline with spike
detection, gap identification, and notable event extraction.
"""

from fastapi import APIRouter, HTTPException, Depends
from core.store import get_prescanned, get_provider_by_npi
from data.duckdb_client import query_async, get_parquet_path
from routes.auth import require_user

router = APIRouter(prefix="/api/providers", tags=["timeline"], dependencies=[Depends(require_user)])


def _detect_spikes_and_events(months: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Analyse monthly data to:
    1. Flag months where billing > 2x the provider's own average (spike).
    2. Generate a list of notable events (first/last billing, gaps > 3 months, spikes).

    Returns (enriched_months, events).
    """
    if not months:
        return [], []

    paid_values = [m.get("total_paid", 0) for m in months]
    avg_paid = sum(paid_values) / len(paid_values) if paid_values else 0

    enriched = []
    events: list[dict] = []

    # First billing
    events.append({
        "type": "first_billing",
        "month": months[0]["month"],
        "description": f"First claim activity recorded",
    })

    # Last billing
    if len(months) > 1:
        events.append({
            "type": "last_billing",
            "month": months[-1]["month"],
            "description": f"Most recent claim activity",
        })

    prev_month_str = None
    for m in months:
        is_spike = avg_paid > 0 and m.get("total_paid", 0) > 2 * avg_paid
        enriched.append({
            **m,
            "is_spike": is_spike,
            "avg_paid": round(avg_paid, 2),
        })
        if is_spike:
            events.append({
                "type": "spike",
                "month": m["month"],
                "description": (
                    f"Billing spike: ${m['total_paid']:,.0f} "
                    f"({m['total_paid'] / avg_paid:.1f}x provider average)"
                ),
                "total_paid": round(m["total_paid"], 2),
                "multiple": round(m["total_paid"] / avg_paid, 2) if avg_paid else 0,
            })

        # Gap detection: if more than 3 months between consecutive entries
        if prev_month_str:
            try:
                prev_y, prev_m_num = int(prev_month_str[:4]), int(prev_month_str[5:7])
                cur_y, cur_m_num = int(m["month"][:4]), int(m["month"][5:7])
                gap = (cur_y * 12 + cur_m_num) - (prev_y * 12 + prev_m_num)
                if gap > 3:
                    events.append({
                        "type": "gap",
                        "month": m["month"],
                        "description": f"{gap}-month gap in billing (from {prev_month_str} to {m['month']})",
                        "gap_months": gap,
                        "gap_start": prev_month_str,
                        "gap_end": m["month"],
                    })
            except (ValueError, IndexError):
                pass

        prev_month_str = m["month"]

    # Sort events chronologically
    events.sort(key=lambda e: e.get("month", ""))

    return enriched, events


@router.get("/{npi}/timeline-analysis")
async def get_timeline_analysis(npi: str):
    """
    Enhanced provider timeline with spike detection and notable events.

    Returns monthly aggregates enriched with spike flags, plus a list of
    notable events (first/last billing, gaps > 3 months, spike months).
    """

    # Try prescan cache first
    cached = get_provider_by_npi(npi)
    raw_timeline = None

    if cached and cached.get("timeline"):
        raw_timeline = cached["timeline"]

    if not raw_timeline:
        # Fallback: query Parquet directly
        sql = f"""
        SELECT
            CLAIM_FROM_MONTH                    AS month,
            SUM(TOTAL_PAID)                     AS total_paid,
            SUM(TOTAL_CLAIM_COUNT)              AS claim_count,
            COUNT(DISTINCT HCPCS_CODE)          AS unique_hcpcs_count,
            SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS unique_beneficiaries
        FROM read_parquet('{get_parquet_path()}')
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
        GROUP BY CLAIM_FROM_MONTH
        ORDER BY CLAIM_FROM_MONTH ASC
        """
        try:
            raw_timeline = await query_async(sql)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

    if not raw_timeline:
        return {
            "npi": npi,
            "months": [],
            "events": [],
            "summary": {
                "total_months": 0,
                "avg_monthly_paid": 0,
                "max_monthly_paid": 0,
                "spike_count": 0,
                "gap_count": 0,
            },
        }

    # Normalise field names (cache uses total_claims/total_unique_beneficiaries)
    normalised = []
    for row in raw_timeline:
        normalised.append({
            "month": row.get("month", ""),
            "total_paid": round(float(row.get("total_paid", 0)), 2),
            "claim_count": int(row.get("claim_count") or row.get("total_claims") or 0),
            "unique_hcpcs_count": int(row.get("unique_hcpcs_count") or row.get("distinct_hcpcs") or 0),
            "unique_beneficiaries": int(
                row.get("unique_beneficiaries")
                or row.get("total_unique_beneficiaries")
                or 0
            ),
        })

    enriched, events = _detect_spikes_and_events(normalised)

    paid_values = [m["total_paid"] for m in normalised]

    return {
        "npi": npi,
        "months": enriched,
        "events": events,
        "summary": {
            "total_months": len(normalised),
            "avg_monthly_paid": round(sum(paid_values) / len(paid_values), 2) if paid_values else 0,
            "max_monthly_paid": round(max(paid_values), 2) if paid_values else 0,
            "spike_count": sum(1 for m in enriched if m.get("is_spike")),
            "gap_count": sum(1 for e in events if e["type"] == "gap"),
        },
    }
