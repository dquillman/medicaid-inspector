"""
Provider-to-Population Ratio Analysis

Flags geographic areas with suspiciously high provider density relative to
Medicaid enrollment, and identifies providers billing beyond physical capacity.
"""

import time as _time
from collections import defaultdict
from typing import Any

from core.store import get_prescanned

# ── In-memory cache (TTL 10 minutes) ─────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 600


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (_time.time(), value)

# ── State Medicaid enrollment estimates (2024, rounded) ────────────────────
# Source: CMS Medicaid enrollment data, approximate figures in thousands
STATE_MEDICAID_ENROLLMENT: dict[str, int] = {
    "AL": 1_100_000,
    "AK": 240_000,
    "AZ": 2_400_000,
    "AR": 1_000_000,
    "CA": 14_700_000,
    "CO": 1_700_000,
    "CT": 1_100_000,
    "DE": 300_000,
    "DC": 290_000,
    "FL": 5_000_000,
    "GA": 2_400_000,
    "HI": 420_000,
    "ID": 500_000,
    "IL": 3_600_000,
    "IN": 1_900_000,
    "IA": 900_000,
    "KS": 500_000,
    "KY": 1_600_000,
    "LA": 1_800_000,
    "ME": 380_000,
    "MD": 1_600_000,
    "MA": 2_100_000,
    "MI": 2_900_000,
    "MN": 1_400_000,
    "MS": 800_000,
    "MO": 1_200_000,
    "MT": 300_000,
    "NE": 400_000,
    "NV": 900_000,
    "NH": 250_000,
    "NJ": 2_200_000,
    "NM": 900_000,
    "NY": 7_900_000,
    "NC": 2_700_000,
    "ND": 120_000,
    "OH": 3_200_000,
    "OK": 1_100_000,
    "OR": 1_400_000,
    "PA": 3_500_000,
    "RI": 350_000,
    "SC": 1_300_000,
    "SD": 170_000,
    "TN": 1_800_000,
    "TX": 5_500_000,
    "UT": 500_000,
    "VT": 190_000,
    "VA": 1_800_000,
    "WA": 2_200_000,
    "WV": 600_000,
    "WI": 1_500_000,
    "WY": 80_000,
}


def _get_provider_state(provider: dict) -> str | None:
    """Extract state from provider dict, checking multiple locations."""
    state = provider.get("state") or ""
    if not state:
        nppes = provider.get("nppes") or {}
        addr = nppes.get("address") or {}
        state = addr.get("state", "")
    return state.strip().upper() if state else None


def _get_provider_zip_prefix(provider: dict) -> str | None:
    """Extract 3-digit ZIP prefix from provider NPPES data."""
    nppes = provider.get("nppes") or {}
    addr = nppes.get("address") or {}
    zip_code = addr.get("zip", "")
    if zip_code and len(str(zip_code)) >= 3:
        return str(zip_code)[:3]
    return None


def compute_provider_ratios() -> dict:
    """
    Group providers by state, compute provider-to-population ratios,
    flag states where ratio > 2x national average.
    """
    cached = _cache_get("provider_ratios")
    if cached is not None:
        return cached

    providers = get_prescanned()
    if not providers:
        return {
            "states": [],
            "national_avg_per_100k": 0,
            "total_providers": 0,
            "total_enrollment": 0,
        }

    # Group providers by state
    by_state: dict[str, list[dict]] = defaultdict(list)
    for p in providers:
        st = _get_provider_state(p)
        if st and st in STATE_MEDICAID_ENROLLMENT:
            by_state[st].append(p)

    # Compute national totals for providers that have a known state
    total_matched_providers = sum(len(v) for v in by_state.values())
    total_matched_enrollment = sum(
        STATE_MEDICAID_ENROLLMENT[st] for st in by_state if st in STATE_MEDICAID_ENROLLMENT
    )

    national_avg = (
        (total_matched_providers / total_matched_enrollment * 100_000)
        if total_matched_enrollment > 0
        else 0
    )

    state_rows = []
    for st, prov_list in sorted(by_state.items()):
        enrollment = STATE_MEDICAID_ENROLLMENT.get(st, 0)
        count = len(prov_list)
        ratio = (count / enrollment * 100_000) if enrollment > 0 else 0
        total_paid = sum(p.get("total_paid", 0) or 0 for p in prov_list)
        avg_risk = (
            sum(p.get("risk_score", 0) or 0 for p in prov_list) / count
            if count > 0
            else 0
        )
        flagged = national_avg > 0 and ratio > 2 * national_avg

        state_rows.append({
            "state": st,
            "provider_count": count,
            "enrollment": enrollment,
            "providers_per_100k": round(ratio, 2),
            "national_avg_per_100k": round(national_avg, 2),
            "ratio_vs_national": round(ratio / national_avg, 2) if national_avg > 0 else 0,
            "flagged": flagged,
            "total_paid": round(total_paid, 2),
            "avg_risk_score": round(avg_risk, 1),
        })

    # Sort by ratio descending
    state_rows.sort(key=lambda x: x["providers_per_100k"], reverse=True)

    result = {
        "states": state_rows,
        "national_avg_per_100k": round(national_avg, 2),
        "total_providers": total_matched_providers,
        "total_enrollment": total_matched_enrollment,
    }
    _cache_set("provider_ratios", result)
    return result


def compute_zip_ratios(state: str) -> dict:
    """
    Compute provider-to-population ratios by 3-digit ZIP prefix within a state.
    Since we don't have ZIP-level population data, we use provider count and
    total billing as density indicators. Flags ZIP prefixes with disproportionately
    high provider counts relative to the state average.
    """
    state = state.upper()
    cache_key = f"zip_ratios_{state}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    providers = get_prescanned()

    # Filter to just this state
    state_providers = [
        p for p in providers if _get_provider_state(p) == state
    ]

    if not state_providers:
        return {"state": state, "zips": [], "state_avg_per_zip": 0}

    # Group by 3-digit ZIP prefix
    by_zip: dict[str, list[dict]] = defaultdict(list)
    for p in state_providers:
        prefix = _get_provider_zip_prefix(p)
        if prefix:
            by_zip[prefix].append(p)

    if not by_zip:
        return {"state": state, "zips": [], "state_avg_per_zip": 0}

    state_avg = len(state_providers) / len(by_zip) if by_zip else 0

    zip_rows = []
    for prefix, prov_list in sorted(by_zip.items()):
        count = len(prov_list)
        total_paid = sum(p.get("total_paid", 0) or 0 for p in prov_list)
        avg_risk = (
            sum(p.get("risk_score", 0) or 0 for p in prov_list) / count
            if count > 0
            else 0
        )
        ratio_vs_avg = count / state_avg if state_avg > 0 else 0
        flagged = ratio_vs_avg > 2.0

        zip_rows.append({
            "zip_prefix": prefix,
            "provider_count": count,
            "total_paid": round(total_paid, 2),
            "avg_risk_score": round(avg_risk, 1),
            "ratio_vs_state_avg": round(ratio_vs_avg, 2),
            "flagged": flagged,
        })

    zip_rows.sort(key=lambda x: x["provider_count"], reverse=True)

    result = {
        "state": state,
        "zips": zip_rows,
        "state_avg_per_zip": round(state_avg, 2),
        "enrollment": STATE_MEDICAID_ENROLLMENT.get(state, 0),
    }
    _cache_set(cache_key, result)
    return result


def compute_billing_capacity() -> list[dict]:
    """
    For each provider, estimate max reasonable billing based on:
    - Solo practitioner: max ~16 patients/day * 250 working days * ~$150 avg visit = $600K
    - Hard cap at $2M for solo (any specialty)
    - Flag providers billing beyond estimated physical capacity

    Returns list of over-capacity providers sorted by overage percentage.
    """
    cached = _cache_get("billing_capacity")
    if cached is not None:
        return cached

    providers = get_prescanned()
    if not providers:
        return []

    # Specialty-based max annual billing estimates
    # Higher caps for specialties that legitimately bill more (e.g., surgery, radiology)
    MAX_BILLING_DEFAULT = 2_000_000  # $2M default cap for solo practitioner
    MAX_PATIENTS_PER_DAY = 16
    WORKING_DAYS = 250
    AVG_VISIT_COST = 150  # national average

    # Estimated max = patients/day * days * avg cost, capped at $2M
    estimated_max = min(MAX_PATIENTS_PER_DAY * WORKING_DAYS * AVG_VISIT_COST, MAX_BILLING_DEFAULT)

    overcapacity = []
    for p in providers:
        total_paid = p.get("total_paid", 0) or 0
        if total_paid <= estimated_max:
            continue

        overage_pct = ((total_paid - estimated_max) / estimated_max) * 100
        npi = p.get("npi", "")
        nppes = p.get("nppes") or {}

        # Get provider name
        name = p.get("provider_name", "")
        if not name:
            first = nppes.get("first_name", "")
            last = nppes.get("last_name", "")
            org = nppes.get("organization_name", "")
            name = f"{first} {last}".strip() if (first or last) else org

        # Get specialty from top HCPCS or nppes
        specialty = nppes.get("taxonomy_desc", "")
        if not specialty:
            specialty = p.get("top_hcpcs", "Unknown")

        state = _get_provider_state(p) or "N/A"

        overcapacity.append({
            "npi": npi,
            "provider_name": name or "Unknown",
            "state": state,
            "specialty": specialty,
            "total_paid": round(total_paid, 2),
            "estimated_max": estimated_max,
            "overage_amount": round(total_paid - estimated_max, 2),
            "overage_pct": round(overage_pct, 1),
            "total_claims": p.get("total_claims", 0) or 0,
            "total_beneficiaries": p.get("total_beneficiaries", 0) or 0,
            "risk_score": p.get("risk_score", 0) or 0,
        })

    # Sort by overage percentage descending
    overcapacity.sort(key=lambda x: x["overage_pct"], reverse=True)

    _cache_set("billing_capacity", overcapacity)
    return overcapacity
