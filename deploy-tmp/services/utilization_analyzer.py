"""
Expected vs Actual Utilization Analysis.

Compares provider claims volume against state-level expected utilization rates
(based on Medicaid enrollment estimates) to identify phantom billing and
over-utilization outliers.
"""
from collections import defaultdict
from core.store import get_prescanned

# 2023 Medicaid enrollment estimates by state (millions → raw int)
MEDICAID_ENROLLMENT: dict[str, int] = {
    "AL": 1_100_000,
    "AK": 230_000,
    "AZ": 2_200_000,
    "AR": 1_000_000,
    "CA": 14_700_000,
    "CO": 1_600_000,
    "CT": 1_100_000,
    "DE": 300_000,
    "DC": 280_000,
    "FL": 5_000_000,
    "GA": 2_500_000,
    "HI": 400_000,
    "ID": 460_000,
    "IL": 3_400_000,
    "IN": 1_800_000,
    "IA": 900_000,
    "KS": 470_000,
    "KY": 1_600_000,
    "LA": 1_800_000,
    "ME": 380_000,
    "MD": 1_600_000,
    "MA": 2_000_000,
    "MI": 2_800_000,
    "MN": 1_400_000,
    "MS": 800_000,
    "MO": 1_200_000,
    "MT": 280_000,
    "NE": 380_000,
    "NV": 900_000,
    "NH": 220_000,
    "NJ": 2_100_000,
    "NM": 900_000,
    "NY": 7_900_000,
    "NC": 2_500_000,
    "ND": 120_000,
    "OH": 3_200_000,
    "OK": 1_200_000,
    "OR": 1_400_000,
    "PA": 3_500_000,
    "PR": 1_500_000,
    "RI": 350_000,
    "SC": 1_300_000,
    "SD": 150_000,
    "TN": 1_800_000,
    "TX": 5_500_000,
    "UT": 450_000,
    "VT": 180_000,
    "VA": 1_700_000,
    "WA": 2_100_000,
    "WV": 600_000,
    "WI": 1_500_000,
    "WY": 80_000,
}


def _get_provider_state(provider: dict) -> str:
    """Extract the 2-letter state code from a provider record."""
    # Try NPPES enrichment first, then top-level state field
    nppes = provider.get("nppes") or {}
    state = nppes.get("state") or provider.get("state") or ""
    return state.strip().upper()[:2]


def _get_provider_specialty(provider: dict) -> str:
    """Extract provider specialty from the record."""
    nppes = provider.get("nppes") or {}
    specialty = (
        nppes.get("healthcare_provider_taxonomy_description")
        or provider.get("provider_type")
        or provider.get("specialty")
        or "Unknown"
    )
    return specialty


def _get_provider_name(provider: dict) -> str:
    """Extract provider name from the record."""
    nppes = provider.get("nppes") or {}
    name = (
        nppes.get("provider_name")
        or provider.get("provider_name")
        or provider.get("npi", "Unknown")
    )
    return name


def analyze_by_state() -> list[dict]:
    """
    Group providers by state and compute utilization metrics.
    Returns a list of state-level records sorted by deviation ratio descending.
    """
    providers = get_prescanned()
    if not providers:
        return []

    # Aggregate by state
    state_data: dict[str, dict] = defaultdict(lambda: {
        "total_claims": 0,
        "total_beneficiaries": 0,
        "total_paid": 0.0,
        "provider_count": 0,
    })

    for p in providers:
        state = _get_provider_state(p)
        if not state or len(state) != 2:
            continue
        d = state_data[state]
        d["total_claims"] += int(p.get("total_claims") or 0)
        d["total_beneficiaries"] += int(p.get("total_beneficiaries") or 0)
        d["total_paid"] += float(p.get("total_paid") or 0)
        d["provider_count"] += 1

    # Compute claims per 1000 enrollees for each state
    results = []
    all_claims_per_1000 = []

    for state, d in state_data.items():
        enrollment = MEDICAID_ENROLLMENT.get(state, 0)
        claims_per_1000 = (d["total_claims"] / enrollment * 1000) if enrollment > 0 else 0.0
        all_claims_per_1000.append(claims_per_1000)

        results.append({
            "state": state,
            "enrollment": enrollment,
            "total_claims": d["total_claims"],
            "total_beneficiaries": d["total_beneficiaries"],
            "total_paid": round(d["total_paid"], 2),
            "provider_count": d["provider_count"],
            "claims_per_1000": round(claims_per_1000, 2),
        })

    # Compute national average claims per 1000
    national_avg = (
        sum(all_claims_per_1000) / len(all_claims_per_1000)
        if all_claims_per_1000
        else 0.0
    )

    for r in results:
        r["national_avg_claims_per_1000"] = round(national_avg, 2)
        deviation_pct = (
            ((r["claims_per_1000"] - national_avg) / national_avg * 100)
            if national_avg > 0
            else 0.0
        )
        r["deviation_pct"] = round(deviation_pct, 1)
        r["flagged"] = r["claims_per_1000"] > 2 * national_avg

    results.sort(key=lambda r: r["claims_per_1000"], reverse=True)
    return results


def analyze_outlier_providers(limit: int = 50) -> list[dict]:
    """
    Find individual providers whose utilization far exceeds their state average
    for their specialty. Returns the top N by deviation multiple.
    """
    providers = get_prescanned()
    if not providers:
        return []

    # Build specialty-within-state groups
    # key: (state, specialty) -> list of claims counts
    specialty_state_claims: dict[tuple[str, str], list[int]] = defaultdict(list)
    provider_records: list[tuple[dict, str, str]] = []

    for p in providers:
        state = _get_provider_state(p)
        if not state or len(state) != 2:
            continue
        specialty = _get_provider_specialty(p)
        claims = int(p.get("total_claims") or 0)
        specialty_state_claims[(state, specialty)].append(claims)
        provider_records.append((p, state, specialty))

    # Compute per-(state, specialty) average
    specialty_state_avg: dict[tuple[str, str], float] = {}
    for key, claims_list in specialty_state_claims.items():
        specialty_state_avg[key] = sum(claims_list) / len(claims_list) if claims_list else 0

    # Score each provider
    outliers = []
    for p, state, specialty in provider_records:
        claims = int(p.get("total_claims") or 0)
        avg = specialty_state_avg.get((state, specialty), 0)
        if avg <= 0 or claims <= 0:
            continue

        deviation_multiple = claims / avg
        if deviation_multiple <= 3.0:
            continue

        enrollment = MEDICAID_ENROLLMENT.get(state, 0)
        peer_count = len(specialty_state_claims.get((state, specialty), []))

        # Expected share = 1/peer_count of state specialty total
        total_specialty_claims = sum(specialty_state_claims.get((state, specialty), []))
        expected_claims = total_specialty_claims / peer_count if peer_count > 0 else 0

        outliers.append({
            "npi": p.get("npi", ""),
            "provider_name": _get_provider_name(p),
            "state": state,
            "specialty": specialty,
            "total_claims": claims,
            "total_paid": round(float(p.get("total_paid") or 0), 2),
            "expected_claims": round(expected_claims, 1),
            "state_specialty_avg": round(avg, 1),
            "deviation_multiple": round(deviation_multiple, 2),
            "peer_count": peer_count,
            "risk_score": p.get("risk_score", 0),
        })

    outliers.sort(key=lambda o: o["deviation_multiple"], reverse=True)
    return outliers[:limit]


def analyze_state_providers(state: str) -> list[dict]:
    """
    Return provider-level utilization breakdown for a specific state,
    showing each provider's share of state claims vs expected.
    """
    providers = get_prescanned()
    if not providers:
        return []

    state = state.strip().upper()
    state_providers = []

    for p in providers:
        p_state = _get_provider_state(p)
        if p_state == state:
            state_providers.append(p)

    if not state_providers:
        return []

    total_state_claims = sum(int(p.get("total_claims") or 0) for p in state_providers)
    provider_count = len(state_providers)
    expected_share = 1.0 / provider_count if provider_count > 0 else 0
    enrollment = MEDICAID_ENROLLMENT.get(state, 0)

    results = []
    for p in state_providers:
        claims = int(p.get("total_claims") or 0)
        actual_share = claims / total_state_claims if total_state_claims > 0 else 0
        share_ratio = actual_share / expected_share if expected_share > 0 else 0
        claims_per_1000 = (claims / enrollment * 1000) if enrollment > 0 else 0

        results.append({
            "npi": p.get("npi", ""),
            "provider_name": _get_provider_name(p),
            "specialty": _get_provider_specialty(p),
            "total_claims": claims,
            "total_paid": round(float(p.get("total_paid") or 0), 2),
            "total_beneficiaries": int(p.get("total_beneficiaries") or 0),
            "claims_per_1000": round(claims_per_1000, 4),
            "actual_share_pct": round(actual_share * 100, 3),
            "expected_share_pct": round(expected_share * 100, 3),
            "share_ratio": round(share_ratio, 2),
            "risk_score": p.get("risk_score", 0),
        })

    results.sort(key=lambda r: r["share_ratio"], reverse=True)
    return results
