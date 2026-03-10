"""
State-level demographic data from U.S. Census / ACS (approx. 2023 values).
Used to overlay poverty, income, and Medicaid enrollment against provider billing
for a demographic fraud risk layer.
"""

from typing import Optional

# ── Hardcoded state-level demographics (approx. 2023 ACS) ────────────────────
# Keys: population (thousands → actual), poverty_rate (%), median_income ($),
#        pct_uninsured (%), medicaid_pct (% of pop on Medicaid)

STATE_DEMOGRAPHICS: dict[str, dict] = {
    "AL": {"population": 5108468,  "poverty_rate": 14.8, "median_income": 55727,  "pct_uninsured": 9.5,  "medicaid_pct": 24.0},
    "AK": {"population": 733406,   "poverty_rate": 10.2, "median_income": 77790,  "pct_uninsured": 12.3, "medicaid_pct": 22.5},
    "AZ": {"population": 7359197,  "poverty_rate": 13.5, "median_income": 65913,  "pct_uninsured": 9.8,  "medicaid_pct": 25.3},
    "AR": {"population": 3045637,  "poverty_rate": 16.0, "median_income": 52528,  "pct_uninsured": 8.4,  "medicaid_pct": 28.5},
    "CA": {"population": 38965193, "poverty_rate": 11.0, "median_income": 91905,  "pct_uninsured": 6.6,  "medicaid_pct": 33.5},
    "CO": {"population": 5877610,  "poverty_rate": 9.1,  "median_income": 84954,  "pct_uninsured": 6.7,  "medicaid_pct": 22.0},
    "CT": {"population": 3617176,  "poverty_rate": 9.8,  "median_income": 90213,  "pct_uninsured": 5.3,  "medicaid_pct": 24.8},
    "DE": {"population": 1018396,  "poverty_rate": 11.3, "median_income": 72724,  "pct_uninsured": 6.0,  "medicaid_pct": 27.0},
    "DC": {"population": 678972,   "poverty_rate": 13.2, "median_income": 101722, "pct_uninsured": 3.4,  "medicaid_pct": 30.0},
    "FL": {"population": 22610726, "poverty_rate": 11.4, "median_income": 67917,  "pct_uninsured": 11.4, "medicaid_pct": 22.0},
    "GA": {"population": 11029227, "poverty_rate": 12.7, "median_income": 65030,  "pct_uninsured": 12.0, "medicaid_pct": 21.5},
    "HI": {"population": 1440196,  "poverty_rate": 9.3,  "median_income": 88005,  "pct_uninsured": 4.2,  "medicaid_pct": 21.0},
    "ID": {"population": 1964726,  "poverty_rate": 10.6, "median_income": 65988,  "pct_uninsured": 9.5,  "medicaid_pct": 23.0},
    "IL": {"population": 12549689, "poverty_rate": 10.7, "median_income": 74235,  "pct_uninsured": 6.4,  "medicaid_pct": 25.5},
    "IN": {"population": 6862199,  "poverty_rate": 11.4, "median_income": 62056,  "pct_uninsured": 7.8,  "medicaid_pct": 23.2},
    "IA": {"population": 3207004,  "poverty_rate": 10.4, "median_income": 65573,  "pct_uninsured": 4.7,  "medicaid_pct": 23.0},
    "KS": {"population": 2940546,  "poverty_rate": 10.3, "median_income": 66590,  "pct_uninsured": 8.5,  "medicaid_pct": 15.5},
    "KY": {"population": 4526154,  "poverty_rate": 15.5, "median_income": 55573,  "pct_uninsured": 5.2,  "medicaid_pct": 30.0},
    "LA": {"population": 4573749,  "poverty_rate": 18.6, "median_income": 52087,  "pct_uninsured": 7.6,  "medicaid_pct": 30.5},
    "ME": {"population": 1395722,  "poverty_rate": 10.9, "median_income": 64767,  "pct_uninsured": 5.7,  "medicaid_pct": 26.5},
    "MD": {"population": 6164660,  "poverty_rate": 9.1,  "median_income": 94991,  "pct_uninsured": 5.8,  "medicaid_pct": 22.5},
    "MA": {"population": 7001399,  "poverty_rate": 10.1, "median_income": 96505,  "pct_uninsured": 2.7,  "medicaid_pct": 27.0},
    "MI": {"population": 10037261, "poverty_rate": 13.0, "median_income": 63202,  "pct_uninsured": 5.8,  "medicaid_pct": 27.0},
    "MN": {"population": 5737915,  "poverty_rate": 8.3,  "median_income": 80441,  "pct_uninsured": 4.5,  "medicaid_pct": 21.0},
    "MS": {"population": 2939690,  "poverty_rate": 19.4, "median_income": 48610,  "pct_uninsured": 11.0, "medicaid_pct": 27.0},
    "MO": {"population": 6196156,  "poverty_rate": 12.1, "median_income": 61043,  "pct_uninsured": 8.8,  "medicaid_pct": 21.5},
    "MT": {"population": 1132812,  "poverty_rate": 12.1, "median_income": 60560,  "pct_uninsured": 7.8,  "medicaid_pct": 19.5},
    "NE": {"population": 1978379,  "poverty_rate": 10.0, "median_income": 67614,  "pct_uninsured": 7.2,  "medicaid_pct": 18.0},
    "NV": {"population": 3194176,  "poverty_rate": 11.2, "median_income": 68700,  "pct_uninsured": 10.1, "medicaid_pct": 24.0},
    "NH": {"population": 1402054,  "poverty_rate": 7.2,  "median_income": 88841,  "pct_uninsured": 5.4,  "medicaid_pct": 17.0},
    "NJ": {"population": 9290841,  "poverty_rate": 9.4,  "median_income": 93610,  "pct_uninsured": 7.9,  "medicaid_pct": 21.0},
    "NM": {"population": 2114371,  "poverty_rate": 17.6, "median_income": 53992,  "pct_uninsured": 10.3, "medicaid_pct": 35.0},
    "NY": {"population": 19571216, "poverty_rate": 12.7, "median_income": 75910,  "pct_uninsured": 5.2,  "medicaid_pct": 33.0},
    "NC": {"population": 10835491, "poverty_rate": 12.9, "median_income": 62891,  "pct_uninsured": 9.4,  "medicaid_pct": 23.0},
    "ND": {"population": 783926,   "poverty_rate": 10.8, "median_income": 68131,  "pct_uninsured": 7.0,  "medicaid_pct": 14.0},
    "OH": {"population": 11785935, "poverty_rate": 13.0, "median_income": 61938,  "pct_uninsured": 6.0,  "medicaid_pct": 26.0},
    "OK": {"population": 4053824,  "poverty_rate": 14.5, "median_income": 56956,  "pct_uninsured": 13.7, "medicaid_pct": 23.5},
    "OR": {"population": 4233358,  "poverty_rate": 11.2, "median_income": 71562,  "pct_uninsured": 5.6,  "medicaid_pct": 27.0},
    "PA": {"population": 12961683, "poverty_rate": 11.1, "median_income": 69693,  "pct_uninsured": 5.5,  "medicaid_pct": 24.0},
    "RI": {"population": 1095610,  "poverty_rate": 10.3, "median_income": 72305,  "pct_uninsured": 3.7,  "medicaid_pct": 28.0},
    "SC": {"population": 5373555,  "poverty_rate": 13.8, "median_income": 59318,  "pct_uninsured": 9.8,  "medicaid_pct": 22.0},
    "SD": {"population": 919318,   "poverty_rate": 12.5, "median_income": 63920,  "pct_uninsured": 9.0,  "medicaid_pct": 17.5},
    "TN": {"population": 7126489,  "poverty_rate": 13.4, "median_income": 59695,  "pct_uninsured": 9.2,  "medicaid_pct": 23.0},
    "TX": {"population": 30503301, "poverty_rate": 13.4, "median_income": 67321,  "pct_uninsured": 16.6, "medicaid_pct": 18.5},
    "UT": {"population": 3417734,  "poverty_rate": 8.2,  "median_income": 80196,  "pct_uninsured": 8.6,  "medicaid_pct": 14.0},
    "VT": {"population": 647464,   "poverty_rate": 10.3, "median_income": 69543,  "pct_uninsured": 4.0,  "medicaid_pct": 28.0},
    "VA": {"population": 8683619,  "poverty_rate": 9.6,  "median_income": 85873,  "pct_uninsured": 7.3,  "medicaid_pct": 20.0},
    "WA": {"population": 7812880,  "poverty_rate": 10.0, "median_income": 84247,  "pct_uninsured": 5.7,  "medicaid_pct": 24.5},
    "WV": {"population": 1770071,  "poverty_rate": 17.5, "median_income": 50884,  "pct_uninsured": 5.5,  "medicaid_pct": 33.0},
    "WI": {"population": 5910955,  "poverty_rate": 10.6, "median_income": 67125,  "pct_uninsured": 5.0,  "medicaid_pct": 22.0},
    "WY": {"population": 584057,   "poverty_rate": 9.6,  "median_income": 69264,  "pct_uninsured": 10.8, "medicaid_pct": 12.0},
}


def get_state_demographics(state: str) -> Optional[dict]:
    """Return demographic data for a single state abbreviation (e.g. 'MS')."""
    data = STATE_DEMOGRAPHICS.get(state.upper())
    if data is None:
        return None
    return {"state": state.upper(), **data}


def get_all_demographics() -> dict[str, dict]:
    """Return demographic data for all states."""
    return {st: {"state": st, **d} for st, d in STATE_DEMOGRAPHICS.items()}


def compute_demographic_risk(state: str, provider_billing_per_capita: float = 0.0) -> float:
    """
    Compute a 0-100 demographic risk score for a state.

    Higher risk when:
      - High poverty rate (weight 30)
      - High Medicaid enrollment pct (weight 20)
      - Low median income (weight 15)
      - High uninsured pct (weight 10)
      - High provider billing per capita relative to state income (weight 25)

    Returns 0.0 if state is not found.
    """
    data = STATE_DEMOGRAPHICS.get(state.upper())
    if data is None:
        return 0.0

    # Normalize each factor to 0-1 range using dataset bounds
    all_poverty = [d["poverty_rate"] for d in STATE_DEMOGRAPHICS.values()]
    all_income = [d["median_income"] for d in STATE_DEMOGRAPHICS.values()]
    all_unins = [d["pct_uninsured"] for d in STATE_DEMOGRAPHICS.values()]
    all_medicaid = [d["medicaid_pct"] for d in STATE_DEMOGRAPHICS.values()]

    def normalize(val: float, vals: list[float], invert: bool = False) -> float:
        lo, hi = min(vals), max(vals)
        if hi == lo:
            return 0.5
        n = (val - lo) / (hi - lo)
        return (1.0 - n) if invert else n

    poverty_n = normalize(data["poverty_rate"], all_poverty)
    income_n = normalize(data["median_income"], all_income, invert=True)  # lower income = higher risk
    unins_n = normalize(data["pct_uninsured"], all_unins)
    medicaid_n = normalize(data["medicaid_pct"], all_medicaid)

    # Billing per capita factor: high billing relative to income is suspicious
    if provider_billing_per_capita > 0 and data["median_income"] > 0:
        billing_ratio = provider_billing_per_capita / data["median_income"]
        # Cap at 1.0 (if billing/capita exceeds median income, full risk)
        billing_n = min(billing_ratio * 10, 1.0)  # scale up since ratios are small
    else:
        billing_n = 0.0

    score = (
        poverty_n * 30 +
        medicaid_n * 20 +
        income_n * 15 +
        unins_n * 10 +
        billing_n * 25
    )

    return round(min(score, 100.0), 1)
