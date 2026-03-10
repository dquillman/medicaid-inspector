"""
State Enrollment Trends vs Billing Growth — divergence detection.

Compares hardcoded Medicaid enrollment data (2018-2024) against actual
billing growth from prescan cache to identify states where billing is
growing faster than enrollment (a fraud indicator).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.store import get_prescanned

# ---------------------------------------------------------------------------
# Hardcoded approximate Medicaid enrollment by state, 2018-2024 (millions)
# Most states saw enrollment spike during COVID 2020-2022, then decline
# after PHE unwinding began mid-2023.
# ---------------------------------------------------------------------------
STATE_ENROLLMENT: dict[str, dict[int, float]] = {
    "AL": {2018: 0.90, 2019: 0.89, 2020: 0.94, 2021: 1.03, 2022: 1.08, 2023: 1.02, 2024: 0.93},
    "AK": {2018: 0.19, 2019: 0.19, 2020: 0.20, 2021: 0.22, 2022: 0.23, 2023: 0.22, 2024: 0.20},
    "AZ": {2018: 1.85, 2019: 1.82, 2020: 1.95, 2021: 2.20, 2022: 2.38, 2023: 2.28, 2024: 2.10},
    "AR": {2018: 0.92, 2019: 0.91, 2020: 0.96, 2021: 1.06, 2022: 1.12, 2023: 1.05, 2024: 0.95},
    "CA": {2018: 13.20, 2019: 13.00, 2020: 13.60, 2021: 14.50, 2022: 15.20, 2023: 14.70, 2024: 13.80},
    "CO": {2018: 1.30, 2019: 1.28, 2020: 1.38, 2021: 1.52, 2022: 1.62, 2023: 1.55, 2024: 1.42},
    "CT": {2018: 0.85, 2019: 0.84, 2020: 0.90, 2021: 1.00, 2022: 1.06, 2023: 1.01, 2024: 0.92},
    "DE": {2018: 0.24, 2019: 0.24, 2020: 0.25, 2021: 0.28, 2022: 0.30, 2023: 0.28, 2024: 0.26},
    "FL": {2018: 4.20, 2019: 4.15, 2020: 4.48, 2021: 5.00, 2022: 5.35, 2023: 5.10, 2024: 4.65},
    "GA": {2018: 2.05, 2019: 2.02, 2020: 2.15, 2021: 2.40, 2022: 2.58, 2023: 2.45, 2024: 2.22},
    "HI": {2018: 0.36, 2019: 0.35, 2020: 0.37, 2021: 0.40, 2022: 0.42, 2023: 0.40, 2024: 0.37},
    "ID": {2018: 0.33, 2019: 0.33, 2020: 0.36, 2021: 0.41, 2022: 0.44, 2023: 0.42, 2024: 0.38},
    "IL": {2018: 3.10, 2019: 3.05, 2020: 3.28, 2021: 3.58, 2022: 3.75, 2023: 3.60, 2024: 3.30},
    "IN": {2018: 1.50, 2019: 1.48, 2020: 1.58, 2021: 1.72, 2022: 1.82, 2023: 1.73, 2024: 1.58},
    "IA": {2018: 0.75, 2019: 0.74, 2020: 0.79, 2021: 0.86, 2022: 0.91, 2023: 0.86, 2024: 0.78},
    "KS": {2018: 0.42, 2019: 0.41, 2020: 0.44, 2021: 0.49, 2022: 0.52, 2023: 0.49, 2024: 0.44},
    "KY": {2018: 1.40, 2019: 1.38, 2020: 1.48, 2021: 1.62, 2022: 1.70, 2023: 1.62, 2024: 1.48},
    "LA": {2018: 1.65, 2019: 1.63, 2020: 1.73, 2021: 1.88, 2022: 1.98, 2023: 1.88, 2024: 1.72},
    "ME": {2018: 0.28, 2019: 0.28, 2020: 0.31, 2021: 0.35, 2022: 0.38, 2023: 0.36, 2024: 0.33},
    "MD": {2018: 1.38, 2019: 1.36, 2020: 1.46, 2021: 1.60, 2022: 1.68, 2023: 1.60, 2024: 1.46},
    "MA": {2018: 1.85, 2019: 1.83, 2020: 1.95, 2021: 2.10, 2022: 2.20, 2023: 2.12, 2024: 1.98},
    "MI": {2018: 2.60, 2019: 2.55, 2020: 2.72, 2021: 2.95, 2022: 3.10, 2023: 2.98, 2024: 2.75},
    "MN": {2018: 1.10, 2019: 1.08, 2020: 1.16, 2021: 1.28, 2022: 1.38, 2023: 1.32, 2024: 1.20},
    "MS": {2018: 0.75, 2019: 0.74, 2020: 0.78, 2021: 0.85, 2022: 0.90, 2023: 0.85, 2024: 0.77},
    "MO": {2018: 0.98, 2019: 0.96, 2020: 1.04, 2021: 1.18, 2022: 1.28, 2023: 1.20, 2024: 1.08},
    "MT": {2018: 0.27, 2019: 0.27, 2020: 0.29, 2021: 0.32, 2022: 0.34, 2023: 0.32, 2024: 0.29},
    "NE": {2018: 0.28, 2019: 0.28, 2020: 0.30, 2021: 0.34, 2022: 0.37, 2023: 0.35, 2024: 0.31},
    "NV": {2018: 0.68, 2019: 0.67, 2020: 0.73, 2021: 0.85, 2022: 0.92, 2023: 0.87, 2024: 0.78},
    "NH": {2018: 0.18, 2019: 0.18, 2020: 0.19, 2021: 0.21, 2022: 0.23, 2023: 0.22, 2024: 0.20},
    "NJ": {2018: 1.82, 2019: 1.80, 2020: 1.95, 2021: 2.15, 2022: 2.28, 2023: 2.18, 2024: 2.00},
    "NM": {2018: 0.82, 2019: 0.81, 2020: 0.87, 2021: 0.95, 2022: 1.00, 2023: 0.95, 2024: 0.87},
    "NY": {2018: 6.50, 2019: 6.40, 2020: 6.80, 2021: 7.40, 2022: 7.80, 2023: 7.50, 2024: 7.00},
    "NC": {2018: 2.10, 2019: 2.08, 2020: 2.22, 2021: 2.45, 2022: 2.60, 2023: 2.48, 2024: 2.28},
    "ND": {2018: 0.10, 2019: 0.10, 2020: 0.11, 2021: 0.12, 2022: 0.13, 2023: 0.12, 2024: 0.11},
    "OH": {2018: 3.00, 2019: 2.95, 2020: 3.15, 2021: 3.42, 2022: 3.58, 2023: 3.42, 2024: 3.15},
    "OK": {2018: 0.78, 2019: 0.77, 2020: 0.83, 2021: 0.98, 2022: 1.08, 2023: 1.02, 2024: 0.92},
    "OR": {2018: 1.05, 2019: 1.03, 2020: 1.12, 2021: 1.28, 2022: 1.38, 2023: 1.32, 2024: 1.20},
    "PA": {2018: 2.90, 2019: 2.85, 2020: 3.05, 2021: 3.35, 2022: 3.52, 2023: 3.38, 2024: 3.10},
    "RI": {2018: 0.30, 2019: 0.30, 2020: 0.32, 2021: 0.35, 2022: 0.37, 2023: 0.35, 2024: 0.32},
    "SC": {2018: 1.10, 2019: 1.08, 2020: 1.15, 2021: 1.28, 2022: 1.38, 2023: 1.30, 2024: 1.18},
    "SD": {2018: 0.12, 2019: 0.12, 2020: 0.13, 2021: 0.14, 2022: 0.15, 2023: 0.14, 2024: 0.13},
    "TN": {2018: 1.52, 2019: 1.50, 2020: 1.60, 2021: 1.75, 2022: 1.85, 2023: 1.76, 2024: 1.62},
    "TX": {2018: 4.30, 2019: 4.25, 2020: 4.58, 2021: 5.10, 2022: 5.48, 2023: 5.22, 2024: 4.78},
    "UT": {2018: 0.35, 2019: 0.35, 2020: 0.38, 2021: 0.43, 2022: 0.46, 2023: 0.44, 2024: 0.40},
    "VT": {2018: 0.18, 2019: 0.18, 2020: 0.19, 2021: 0.21, 2022: 0.22, 2023: 0.21, 2024: 0.19},
    "VA": {2018: 1.42, 2019: 1.45, 2020: 1.60, 2021: 1.82, 2022: 1.98, 2023: 1.88, 2024: 1.70},
    "WA": {2018: 1.85, 2019: 1.82, 2020: 1.98, 2021: 2.20, 2022: 2.35, 2023: 2.25, 2024: 2.05},
    "WV": {2018: 0.55, 2019: 0.54, 2020: 0.58, 2021: 0.62, 2022: 0.65, 2023: 0.62, 2024: 0.57},
    "WI": {2018: 1.20, 2019: 1.18, 2020: 1.28, 2021: 1.42, 2022: 1.50, 2023: 1.43, 2024: 1.30},
    "WY": {2018: 0.06, 2019: 0.06, 2020: 0.07, 2021: 0.08, 2022: 0.08, 2023: 0.08, 2024: 0.07},
    "DC": {2018: 0.27, 2019: 0.27, 2020: 0.29, 2021: 0.32, 2022: 0.34, 2023: 0.32, 2024: 0.29},
}

# All years in the dataset
YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

# Divergence thresholds
DIVERGENCE_THRESHOLD_PCT = 20.0  # billing growth must exceed enrollment growth by this %
CONSECUTIVE_YEARS_FLAG = 2       # need this many consecutive divergent years to flag


def _extract_year(month_str: str | None) -> int | None:
    """Extract year from a month string like '2021-03' or '202103'."""
    if not month_str:
        return None
    s = str(month_str).replace("-", "").replace("/", "")
    try:
        return int(s[:4])
    except (ValueError, IndexError):
        return None


def _aggregate_billing_by_state_year() -> dict[str, dict[int, float]]:
    """
    From prescan cache, aggregate total billing ($) by state and year.
    Uses timeline data for year breakdown; falls back to total_paid split
    evenly if no timeline is available.
    """
    billing: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    providers = get_prescanned()

    for p in providers:
        state = (p.get("state") or "").strip().upper()
        if not state or len(state) != 2:
            # Try NPPES enriched state
            nppes = p.get("nppes") or {}
            state = (nppes.get("state") or "").strip().upper()
        if not state or len(state) != 2:
            continue

        timeline = p.get("timeline") or []
        if timeline:
            for entry in timeline:
                year = _extract_year(entry.get("month"))
                paid = float(entry.get("total_paid") or 0)
                if year and year in YEARS and paid > 0:
                    billing[state][year] += paid
        else:
            # No timeline — attribute total_paid to the last year available
            total = float(p.get("total_paid") or 0)
            if total > 0:
                billing[state][2024] += total

    return dict(billing)


def compute_trend_divergence() -> list[dict[str, Any]]:
    """
    For each state: compute year-over-year enrollment vs billing growth,
    flag divergence where billing growth outpaces enrollment growth
    by more than DIVERGENCE_THRESHOLD_PCT for CONSECUTIVE_YEARS_FLAG+ years.

    Returns a list of state records sorted by divergence_score descending.
    """
    billing_by_state = _aggregate_billing_by_state_year()
    results: list[dict[str, Any]] = []

    for state, enrollment_by_year in STATE_ENROLLMENT.items():
        state_billing = billing_by_state.get(state, {})

        yearly_data: list[dict[str, Any]] = []
        for year in YEARS:
            enrollment = enrollment_by_year.get(year, 0)
            billing = state_billing.get(year, 0)
            billing_per_enrollee = (billing / (enrollment * 1_000_000)) if enrollment > 0 else 0
            yearly_data.append({
                "year": year,
                "enrollment_millions": enrollment,
                "total_billing": round(billing, 2),
                "billing_per_enrollee": round(billing_per_enrollee, 2),
            })

        # Compute YoY changes
        yoy_data: list[dict[str, Any]] = []
        for i in range(1, len(yearly_data)):
            prev = yearly_data[i - 1]
            curr = yearly_data[i]

            enrollment_change = 0.0
            if prev["enrollment_millions"] > 0:
                enrollment_change = ((curr["enrollment_millions"] - prev["enrollment_millions"])
                                     / prev["enrollment_millions"] * 100)

            billing_change = 0.0
            if prev["total_billing"] > 0:
                billing_change = ((curr["total_billing"] - prev["total_billing"])
                                  / prev["total_billing"] * 100)

            divergence = billing_change - enrollment_change
            is_divergent = divergence > DIVERGENCE_THRESHOLD_PCT

            yoy_data.append({
                "year": curr["year"],
                "enrollment_change_pct": round(enrollment_change, 1),
                "billing_change_pct": round(billing_change, 1),
                "divergence_pct": round(divergence, 1),
                "is_divergent": is_divergent,
            })

        # Find max consecutive divergent years
        max_consecutive = 0
        current_streak = 0
        total_divergence_score = 0.0
        for yoy in yoy_data:
            if yoy["is_divergent"]:
                current_streak += 1
                total_divergence_score += yoy["divergence_pct"]
                max_consecutive = max(max_consecutive, current_streak)
            else:
                current_streak = 0

        flagged = max_consecutive >= CONSECUTIVE_YEARS_FLAG
        has_billing_data = any(y["total_billing"] > 0 for y in yearly_data)

        # Divergence score: sum of divergence_pct in divergent years, weighted by consecutive count
        divergence_score = round(total_divergence_score * (max_consecutive / max(len(yoy_data), 1)), 1)

        # Enrollment trend direction (overall)
        first_enrollment = yearly_data[0]["enrollment_millions"]
        last_enrollment = yearly_data[-1]["enrollment_millions"]
        enrollment_trend = "flat"
        if first_enrollment > 0:
            overall_enrollment_change = (last_enrollment - first_enrollment) / first_enrollment * 100
            if overall_enrollment_change > 5:
                enrollment_trend = "up"
            elif overall_enrollment_change < -5:
                enrollment_trend = "down"

        # Billing trend direction (overall)
        first_billing = next((y["total_billing"] for y in yearly_data if y["total_billing"] > 0), 0)
        last_billing = next((y["total_billing"] for y in reversed(yearly_data) if y["total_billing"] > 0), 0)
        billing_trend = "flat"
        if first_billing > 0:
            overall_billing_change = (last_billing - first_billing) / first_billing * 100
            if overall_billing_change > 10:
                billing_trend = "up"
            elif overall_billing_change < -10:
                billing_trend = "down"

        results.append({
            "state": state,
            "has_billing_data": has_billing_data,
            "enrollment_trend": enrollment_trend,
            "billing_trend": billing_trend,
            "divergence_score": divergence_score if has_billing_data else 0.0,
            "consecutive_divergent_years": max_consecutive,
            "flagged": flagged and has_billing_data,
            "yearly": yearly_data,
            "yoy": yoy_data,
        })

    # Sort by divergence score descending, flagged first
    results.sort(key=lambda r: (r["flagged"], r["divergence_score"]), reverse=True)
    return results


def get_state_detail(state: str) -> dict[str, Any] | None:
    """Get detailed trend data for a single state."""
    state = state.upper().strip()
    all_trends = compute_trend_divergence()
    for record in all_trends:
        if record["state"] == state:
            return record
    return None
