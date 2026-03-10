"""
Temporal Anomaly Detection Service.

Analyzes provider billing patterns over time to detect:
- Day-of-week distribution anomalies (estimated from monthly data)
- Monthly trend anomalies (spikes, drops, z-score outliers)
- Impossible day volumes (>24h of services extrapolated from monthly volume)
- Seasonal anomalies (billing patterns vs expected seasonal norms)
- Sudden practice changes (abrupt shifts in billing codes or volumes)
"""

import logging
import math
from typing import Optional

from data.duckdb_client import query_async, get_parquet_path

log = logging.getLogger(__name__)

# US federal holidays by month (rough weighting — months with more holidays
# have fewer business days, so higher per-day billing is expected)
_HOLIDAY_MONTHS = {1: 2, 2: 1, 5: 1, 7: 1, 9: 1, 10: 1, 11: 2, 12: 1}
_BUSINESS_DAYS_BY_MONTH = {
    1: 20, 2: 19, 3: 23, 4: 21, 5: 21, 6: 22,
    7: 21, 8: 23, 9: 21, 10: 22, 11: 20, 12: 21,
}

# Typical seasonal indices for Medicaid billing (empirical baseline).
# Values > 1 = higher-than-average billing expected; < 1 = lower.
_SEASONAL_INDEX = {
    1: 0.95, 2: 0.97, 3: 1.05, 4: 1.02, 5: 1.00, 6: 1.00,
    7: 0.98, 8: 1.00, 9: 1.03, 10: 1.05, 11: 1.00, 12: 0.95,
}


def _z_score(value: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return (value - mean) / std


def _severity_from_z(z: float) -> str:
    az = abs(z)
    if az >= 3.0:
        return "CRITICAL"
    if az >= 2.5:
        return "HIGH"
    if az >= 2.0:
        return "MEDIUM"
    return "LOW"


async def analyze_provider_temporal(npi: str) -> dict:
    """
    Full temporal analysis for a single provider.

    Returns:
    - day_of_week_distribution: estimated weekday/weekend split
    - monthly_trend: monthly billing with anomaly flags
    - detected_anomalies: list of detected temporal anomalies
    - impossible_days: months where daily volume appears impossible
    """
    src = f"read_parquet('{get_parquet_path()}')"

    # Get monthly data for this provider
    monthly_sql = f"""
        SELECT
            CLAIM_FROM_MONTH               AS month,
            SUM(TOTAL_PAID)                AS total_paid,
            SUM(TOTAL_CLAIMS)              AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_beneficiaries,
            COUNT(DISTINCT HCPCS_CODE)     AS distinct_hcpcs
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
        GROUP BY CLAIM_FROM_MONTH
        ORDER BY CLAIM_FROM_MONTH ASC
    """

    # Get HCPCS distribution by month for practice-change detection
    hcpcs_sql = f"""
        SELECT
            CLAIM_FROM_MONTH               AS month,
            HCPCS_CODE                     AS hcpcs_code,
            SUM(TOTAL_PAID)                AS total_paid,
            SUM(TOTAL_CLAIMS)              AS total_claims
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
        GROUP BY CLAIM_FROM_MONTH, HCPCS_CODE
        ORDER BY CLAIM_FROM_MONTH ASC, TOTAL_PAID DESC
    """

    monthly_rows = await query_async(monthly_sql)
    hcpcs_rows = await query_async(hcpcs_sql)

    if not monthly_rows:
        return {
            "npi": npi,
            "day_of_week_distribution": [],
            "monthly_trend": [],
            "detected_anomalies": [],
            "impossible_days": [],
            "summary": {"total_months": 0, "anomaly_count": 0},
        }

    # ── 1. Monthly trend with anomaly flags ────────────────────────
    paid_values = [r["total_paid"] or 0 for r in monthly_rows]
    claims_values = [r["total_claims"] or 0 for r in monthly_rows]

    mean_paid = sum(paid_values) / len(paid_values) if paid_values else 0
    std_paid = math.sqrt(sum((v - mean_paid) ** 2 for v in paid_values) / len(paid_values)) if len(paid_values) > 1 else 0
    mean_claims = sum(claims_values) / len(claims_values) if claims_values else 0
    std_claims = math.sqrt(sum((v - mean_claims) ** 2 for v in claims_values) / len(claims_values)) if len(claims_values) > 1 else 0

    monthly_trend = []
    for row in monthly_rows:
        paid = row["total_paid"] or 0
        claims = row["total_claims"] or 0
        z_paid = _z_score(paid, mean_paid, std_paid)
        z_claims = _z_score(claims, mean_claims, std_claims)
        is_anomaly = abs(z_paid) >= 2.0 or abs(z_claims) >= 2.0
        monthly_trend.append({
            "month": row["month"],
            "total_paid": round(paid, 2),
            "total_claims": claims,
            "total_beneficiaries": row["total_beneficiaries"] or 0,
            "distinct_hcpcs": row["distinct_hcpcs"] or 0,
            "z_score_paid": round(z_paid, 2),
            "z_score_claims": round(z_claims, 2),
            "is_anomaly": is_anomaly,
            "anomaly_type": (
                "spike" if z_paid >= 2.0 else
                "drop" if z_paid <= -2.0 else
                "claims_spike" if z_claims >= 2.0 else
                "claims_drop" if z_claims <= -2.0 else
                None
            ),
        })

    # ── 2. Day-of-week distribution (estimated) ──────────────────
    # Since we only have monthly data, we estimate weekday vs weekend
    # billing based on business days in each month. If a provider's
    # per-business-day rate is abnormally high for short months (holidays),
    # it suggests possible weekend/holiday billing.
    day_of_week = _estimate_day_distribution(monthly_rows)

    # ── 3. Impossible day volumes ────────────────────────────────
    impossible_days = _detect_impossible_days(monthly_rows)

    # ── 4. Seasonal anomalies ───────────────────────────────────
    seasonal_anomalies = _detect_seasonal_anomalies(monthly_rows, mean_paid)

    # ── 5. Sudden practice changes ──────────────────────────────
    practice_changes = _detect_practice_changes(hcpcs_rows, monthly_rows)

    # ── 6. Month-over-month volatility ──────────────────────────
    mom_anomalies = _detect_mom_volatility(monthly_rows)

    # ── Aggregate all detected anomalies ─────────────────────────
    detected_anomalies = []

    # From monthly trend spikes/drops
    for mt in monthly_trend:
        if mt["is_anomaly"]:
            detected_anomalies.append({
                "type": "billing_spike" if mt["anomaly_type"] in ("spike", "claims_spike") else "billing_drop",
                "date_range": mt["month"],
                "severity": _severity_from_z(max(abs(mt["z_score_paid"]), abs(mt["z_score_claims"]))),
                "description": (
                    f"{'Billing spike' if 'spike' in (mt['anomaly_type'] or '') else 'Billing drop'} in {mt['month']}: "
                    f"${mt['total_paid']:,.0f} paid ({mt['z_score_paid']:+.1f} std dev from mean), "
                    f"{mt['total_claims']} claims ({mt['z_score_claims']:+.1f} std dev)"
                ),
                "z_score": max(abs(mt["z_score_paid"]), abs(mt["z_score_claims"])),
            })

    # From impossible days
    for imp in impossible_days:
        detected_anomalies.append({
            "type": "impossible_volume",
            "date_range": imp["month"],
            "severity": "CRITICAL" if imp["estimated_daily_hours"] > 48 else "HIGH",
            "description": (
                f"Estimated {imp['estimated_daily_hours']:.1f} hours/day of services in {imp['month']} "
                f"({imp['total_claims']} claims over ~{imp['business_days']} business days = "
                f"{imp['claims_per_day']:.1f} claims/day)"
            ),
            "z_score": imp["estimated_daily_hours"] / 24.0,
        })

    # From seasonal anomalies
    detected_anomalies.extend(seasonal_anomalies)

    # From practice changes
    detected_anomalies.extend(practice_changes)

    # From month-over-month volatility
    detected_anomalies.extend(mom_anomalies)

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    detected_anomalies.sort(key=lambda a: (severity_order.get(a["severity"], 4), a.get("date_range", "")))

    return {
        "npi": npi,
        "day_of_week_distribution": day_of_week,
        "monthly_trend": monthly_trend,
        "detected_anomalies": detected_anomalies,
        "impossible_days": impossible_days,
        "summary": {
            "total_months": len(monthly_rows),
            "anomaly_count": len(detected_anomalies),
            "critical_count": sum(1 for a in detected_anomalies if a["severity"] == "CRITICAL"),
            "high_count": sum(1 for a in detected_anomalies if a["severity"] == "HIGH"),
            "mean_monthly_paid": round(mean_paid, 2),
            "std_monthly_paid": round(std_paid, 2),
        },
    }


def _estimate_day_distribution(monthly_rows: list[dict]) -> list[dict]:
    """
    Estimate day-of-week distribution from monthly data.
    We compute per-business-day billing rate and flag months
    where the rate is high for holiday-heavy months.
    """
    # Build a synthetic weekday vs weekend estimate
    total_weekday_claims = 0
    total_weekend_claims = 0
    months_analyzed = 0

    for row in monthly_rows:
        month_str = row.get("month", "")
        if not month_str or len(month_str) < 7:
            continue
        try:
            month_num = int(month_str[5:7])
        except (ValueError, IndexError):
            continue

        claims = row.get("total_claims", 0) or 0
        biz_days = _BUSINESS_DAYS_BY_MONTH.get(month_num, 22)
        # Total days in month (approx 30)
        total_days = 30
        weekend_days = total_days - biz_days

        # Distribute claims: assume most billing is weekday
        # but compute ratio that would explain monthly total
        weekday_claims = claims * (biz_days / total_days)
        weekend_claims = claims * (weekend_days / total_days)

        total_weekday_claims += weekday_claims
        total_weekend_claims += weekend_claims
        months_analyzed += 1

    if months_analyzed == 0:
        return []

    # Build Mon-Sun distribution (proportional estimate)
    total = total_weekday_claims + total_weekend_claims
    if total == 0:
        return []

    weekday_pct = total_weekday_claims / total
    weekend_pct = total_weekend_claims / total

    # Distribute evenly across 5 weekdays and 2 weekend days
    per_weekday = weekday_pct / 5
    per_weekend = weekend_pct / 2

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    avg_claims = total / (months_analyzed * 30) if months_analyzed > 0 else 0

    distribution = []
    for i, day in enumerate(days):
        is_weekend = i >= 5
        pct = per_weekend if is_weekend else per_weekday
        est_claims = round(avg_claims * pct * 30, 0)
        distribution.append({
            "day": day,
            "estimated_claims": est_claims,
            "percentage": round(pct * 100, 1),
            "is_weekend": is_weekend,
            "is_anomalous": False,  # Will be set by system comparison
        })

    return distribution


def _detect_impossible_days(monthly_rows: list[dict]) -> list[dict]:
    """
    Flag months where the volume of claims suggests more than 24 hours
    of services per business day (using ~15 min per claim as baseline).
    """
    impossible = []
    MINUTES_PER_CLAIM = 15  # Conservative estimate

    for row in monthly_rows:
        month_str = row.get("month", "")
        claims = row.get("total_claims", 0) or 0
        if not month_str or len(month_str) < 7 or claims == 0:
            continue

        try:
            month_num = int(month_str[5:7])
        except (ValueError, IndexError):
            continue

        biz_days = _BUSINESS_DAYS_BY_MONTH.get(month_num, 22)
        claims_per_day = claims / biz_days
        daily_minutes = claims_per_day * MINUTES_PER_CLAIM
        daily_hours = daily_minutes / 60

        if daily_hours > 24:
            impossible.append({
                "month": month_str,
                "total_claims": claims,
                "business_days": biz_days,
                "claims_per_day": round(claims_per_day, 1),
                "estimated_daily_hours": round(daily_hours, 1),
                "total_paid": round(row.get("total_paid", 0) or 0, 2),
            })

    return impossible


def _detect_seasonal_anomalies(monthly_rows: list[dict], mean_paid: float) -> list[dict]:
    """
    Compare provider's monthly billing against expected seasonal patterns.
    Flag months where billing deviates significantly from seasonal norm.
    """
    anomalies = []
    if mean_paid == 0 or len(monthly_rows) < 6:
        return anomalies

    for row in monthly_rows:
        month_str = row.get("month", "")
        paid = row.get("total_paid", 0) or 0
        if not month_str or len(month_str) < 7:
            continue

        try:
            month_num = int(month_str[5:7])
        except (ValueError, IndexError):
            continue

        seasonal_idx = _SEASONAL_INDEX.get(month_num, 1.0)
        expected = mean_paid * seasonal_idx
        if expected == 0:
            continue

        ratio = paid / expected
        # Flag if billing is >2x or <0.3x the seasonal expectation
        if ratio > 2.5:
            anomalies.append({
                "type": "seasonal_anomaly",
                "date_range": month_str,
                "severity": "HIGH" if ratio > 3.5 else "MEDIUM",
                "description": (
                    f"Billing in {month_str} was {ratio:.1f}x the expected seasonal level "
                    f"(${paid:,.0f} vs expected ~${expected:,.0f})"
                ),
                "z_score": ratio,
            })
        elif ratio < 0.2 and paid > 0:
            anomalies.append({
                "type": "seasonal_anomaly",
                "date_range": month_str,
                "severity": "MEDIUM",
                "description": (
                    f"Unusually low billing in {month_str}: ${paid:,.0f} "
                    f"(only {ratio:.0%} of expected seasonal level ~${expected:,.0f})"
                ),
                "z_score": -1 / ratio if ratio > 0 else -5.0,
            })

    return anomalies


def _detect_practice_changes(hcpcs_rows: list[dict], monthly_rows: list[dict]) -> list[dict]:
    """
    Detect abrupt shifts in billing codes — e.g., a provider suddenly
    starts billing a new code heavily or abandons their primary code.
    """
    anomalies = []
    if len(monthly_rows) < 4:
        return anomalies

    # Build per-month code distribution
    month_codes: dict[str, dict[str, float]] = {}
    for row in hcpcs_rows:
        month = row.get("month", "")
        code = row.get("hcpcs_code", "")
        paid = row.get("total_paid", 0) or 0
        if not month or not code:
            continue
        if month not in month_codes:
            month_codes[month] = {}
        month_codes[month][code] = paid

    sorted_months = sorted(month_codes.keys())
    if len(sorted_months) < 4:
        return anomalies

    # Compare each month's top code to previous months
    for i in range(3, len(sorted_months)):
        curr_month = sorted_months[i]
        curr_codes = month_codes[curr_month]
        if not curr_codes:
            continue

        # Get top code for current month
        top_code = max(curr_codes, key=curr_codes.get)
        top_paid = curr_codes[top_code]
        total_paid = sum(curr_codes.values())
        if total_paid == 0:
            continue
        top_pct = top_paid / total_paid

        # Check if this top code was present in the previous 3 months
        prev_months = sorted_months[max(0, i - 3):i]
        code_history = []
        for pm in prev_months:
            pm_codes = month_codes.get(pm, {})
            pm_total = sum(pm_codes.values()) or 1
            pm_pct = pm_codes.get(top_code, 0) / pm_total
            code_history.append(pm_pct)

        avg_prev_pct = sum(code_history) / len(code_history) if code_history else 0

        # Flag if a code suddenly became dominant (>50% of billing)
        # but was <10% in previous months
        if top_pct > 0.50 and avg_prev_pct < 0.10:
            anomalies.append({
                "type": "practice_change",
                "date_range": curr_month,
                "severity": "HIGH" if top_pct > 0.75 else "MEDIUM",
                "description": (
                    f"Sudden shift to code {top_code} in {curr_month}: "
                    f"{top_pct:.0%} of billing (was avg {avg_prev_pct:.0%} in prior 3 months)"
                ),
                "z_score": top_pct / max(avg_prev_pct, 0.01),
            })

    return anomalies


def _detect_mom_volatility(monthly_rows: list[dict]) -> list[dict]:
    """
    Detect extreme month-over-month changes in billing volume.
    """
    anomalies = []
    if len(monthly_rows) < 3:
        return anomalies

    # Compute month-over-month changes
    changes = []
    for i in range(1, len(monthly_rows)):
        prev_paid = monthly_rows[i - 1].get("total_paid", 0) or 0
        curr_paid = monthly_rows[i].get("total_paid", 0) or 0
        if prev_paid > 0:
            pct_change = (curr_paid - prev_paid) / prev_paid
            changes.append({
                "month": monthly_rows[i].get("month", ""),
                "prev_month": monthly_rows[i - 1].get("month", ""),
                "pct_change": pct_change,
                "prev_paid": prev_paid,
                "curr_paid": curr_paid,
            })

    if not changes:
        return anomalies

    # Flag extreme changes (>300% increase or >80% decrease)
    for c in changes:
        if c["pct_change"] > 3.0:
            anomalies.append({
                "type": "volume_spike",
                "date_range": f"{c['prev_month']} to {c['month']}",
                "severity": "HIGH" if c["pct_change"] > 5.0 else "MEDIUM",
                "description": (
                    f"Billing surged {c['pct_change']:.0%} from {c['prev_month']} to {c['month']} "
                    f"(${c['prev_paid']:,.0f} -> ${c['curr_paid']:,.0f})"
                ),
                "z_score": c["pct_change"],
            })
        elif c["pct_change"] < -0.80:
            anomalies.append({
                "type": "volume_drop",
                "date_range": f"{c['prev_month']} to {c['month']}",
                "severity": "HIGH" if c["pct_change"] < -0.90 else "MEDIUM",
                "description": (
                    f"Billing dropped {abs(c['pct_change']):.0%} from {c['prev_month']} to {c['month']} "
                    f"(${c['prev_paid']:,.0f} -> ${c['curr_paid']:,.0f})"
                ),
                "z_score": abs(c["pct_change"]),
            })

    return anomalies


async def get_system_temporal_patterns() -> dict:
    """
    System-wide temporal patterns for baseline comparison.
    Returns aggregate monthly distribution across all providers.
    """
    src = f"read_parquet('{get_parquet_path()}')"

    system_sql = f"""
        SELECT
            CLAIM_FROM_MONTH                    AS month,
            SUM(TOTAL_PAID)                     AS total_paid,
            SUM(TOTAL_CLAIMS)                   AS total_claims,
            COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM) AS active_providers,
            SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS total_beneficiaries
        FROM {src}
        GROUP BY CLAIM_FROM_MONTH
        ORDER BY CLAIM_FROM_MONTH ASC
    """

    rows = await query_async(system_sql)
    if not rows:
        return {"monthly": [], "seasonal_index": {}, "summary": {}}

    # Compute system-level statistics
    paid_values = [r["total_paid"] or 0 for r in rows]
    mean_paid = sum(paid_values) / len(paid_values) if paid_values else 0
    std_paid = math.sqrt(sum((v - mean_paid) ** 2 for v in paid_values) / len(paid_values)) if len(paid_values) > 1 else 0

    # Compute actual seasonal index from data
    month_totals: dict[int, list[float]] = {}
    for row in rows:
        month_str = row.get("month", "")
        if not month_str or len(month_str) < 7:
            continue
        try:
            month_num = int(month_str[5:7])
        except (ValueError, IndexError):
            continue
        paid = row.get("total_paid", 0) or 0
        if month_num not in month_totals:
            month_totals[month_num] = []
        month_totals[month_num].append(paid)

    seasonal_index = {}
    if mean_paid > 0:
        for m in range(1, 13):
            vals = month_totals.get(m, [])
            if vals:
                avg = sum(vals) / len(vals)
                seasonal_index[str(m)] = round(avg / mean_paid, 3)

    monthly = []
    for row in rows:
        paid = row["total_paid"] or 0
        z = _z_score(paid, mean_paid, std_paid)
        monthly.append({
            "month": row["month"],
            "total_paid": round(paid, 2),
            "total_claims": row["total_claims"] or 0,
            "active_providers": row["active_providers"] or 0,
            "total_beneficiaries": row["total_beneficiaries"] or 0,
            "z_score": round(z, 2),
            "is_anomaly": abs(z) >= 2.0,
        })

    return {
        "monthly": monthly,
        "seasonal_index": seasonal_index,
        "summary": {
            "total_months": len(rows),
            "mean_monthly_paid": round(mean_paid, 2),
            "std_monthly_paid": round(std_paid, 2),
            "anomalous_months": sum(1 for m in monthly if m["is_anomaly"]),
        },
    }
