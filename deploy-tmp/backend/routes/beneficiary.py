"""
Beneficiary density mapping — overlays Medicaid enrollment data by state
against provider billing volume to flag areas where billing far exceeds
enrolled population.
"""
import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends

from core.enrollment_store import get_enrollment, fetch_enrollment_data, set_enrollment
from core.store import get_prescanned

from routes.auth import require_user

router = APIRouter(prefix="/api/beneficiary", tags=["beneficiary"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


def _build_state_density() -> list[dict]:
    """
    For each state, compute:
      - medicaid_enrollment (from enrollment store)
      - provider_count (from prescan cache)
      - total_billing (sum of total_paid)
      - billing_per_enrollee (total_billing / enrollment)
      - expected_billing_per_enrollee (national average)
      - ratio (actual / expected)
      - flagged (ratio > 1.5)
    """
    enrollment = get_enrollment()
    providers = get_prescanned()

    if not enrollment:
        return []

    # Aggregate provider data by state
    state_data: dict[str, dict] = defaultdict(lambda: {
        "provider_count": 0,
        "total_billing": 0.0,
        "total_claims": 0,
    })

    for p in providers:
        # Get state from nppes enrichment, or from the provider record
        state = ""
        nppes = p.get("nppes") or {}
        if nppes.get("state"):
            state = nppes["state"]
        elif p.get("state"):
            state = p["state"]

        if not state or len(state) != 2:
            continue

        state = state.upper()
        sd = state_data[state]
        sd["provider_count"] += 1
        sd["total_billing"] += float(p.get("total_paid") or 0)
        sd["total_claims"] += int(p.get("total_claims") or 0)

    # Compute national average billing per enrollee
    national_billing = sum(sd["total_billing"] for sd in state_data.values())
    national_enrollment = sum(
        enrollment.get(st, 0) for st in state_data.keys()
    )

    expected_bpe = (
        national_billing / national_enrollment
        if national_enrollment > 0
        else 0.0
    )

    # Build per-state records
    results = []
    for state_code in sorted(set(list(enrollment.keys()) + list(state_data.keys()))):
        enroll = enrollment.get(state_code, 0)
        sd = state_data.get(state_code, {
            "provider_count": 0,
            "total_billing": 0.0,
            "total_claims": 0,
        })

        billing = sd["total_billing"]
        bpe = billing / enroll if enroll > 0 else 0.0
        ratio = bpe / expected_bpe if expected_bpe > 0 else 0.0

        results.append({
            "state": state_code,
            "medicaid_enrollment": enroll,
            "provider_count": sd["provider_count"],
            "total_billing": round(billing, 2),
            "total_claims": sd["total_claims"],
            "billing_per_enrollee": round(bpe, 2),
            "expected_billing_per_enrollee": round(expected_bpe, 2),
            "ratio": round(ratio, 2),
            "flagged": ratio > 1.5,
        })

    return results


@router.get("/density")
async def beneficiary_density():
    """
    Per-state density analysis: enrollment vs billing volume.
    Returns all states with ratio flagging.
    """
    states = _build_state_density()

    if not states:
        return {
            "states": [],
            "national_avg_billing_per_enrollee": 0,
            "total_enrollment": 0,
            "flagged_count": 0,
        }

    total_enrollment = sum(s["medicaid_enrollment"] for s in states)
    flagged_count = sum(1 for s in states if s["flagged"])
    expected_bpe = states[0]["expected_billing_per_enrollee"] if states else 0

    return {
        "states": states,
        "national_avg_billing_per_enrollee": expected_bpe,
        "total_enrollment": total_enrollment,
        "flagged_count": flagged_count,
    }


@router.get("/density/{state}")
async def beneficiary_density_state(state: str):
    """
    Drill-down into a single state showing city-level provider billing
    vs that state's enrollment share.
    """
    state = state.upper()
    enrollment = get_enrollment()
    state_enrollment = enrollment.get(state, 0)

    if not state_enrollment:
        raise HTTPException(404, f"No enrollment data for state: {state}")

    providers = get_prescanned()

    # Group providers by city within this state
    city_data: dict[str, dict] = defaultdict(lambda: {
        "provider_count": 0,
        "total_billing": 0.0,
        "total_claims": 0,
        "providers": [],
    })

    for p in providers:
        p_state = ""
        p_city = ""
        nppes = p.get("nppes") or {}
        if nppes.get("state"):
            p_state = nppes["state"]
            p_city = nppes.get("city", "")
        elif p.get("state"):
            p_state = p["state"]
            p_city = p.get("city", "")

        if not p_state or p_state.upper() != state:
            continue

        city = (p_city or "Unknown").title()
        cd = city_data[city]
        cd["provider_count"] += 1
        cd["total_billing"] += float(p.get("total_paid") or 0)
        cd["total_claims"] += int(p.get("total_claims") or 0)
        cd["providers"].append({
            "npi": p.get("npi"),
            "name": p.get("provider_name") or nppes.get("name", ""),
            "risk_score": p.get("risk_score", 0),
            "total_paid": float(p.get("total_paid") or 0),
        })

    # State total billing for share calculation
    state_total_billing = sum(cd["total_billing"] for cd in city_data.values())
    state_provider_count = sum(cd["provider_count"] for cd in city_data.values())

    cities = []
    for city_name, cd in sorted(city_data.items(), key=lambda x: x[1]["total_billing"], reverse=True):
        billing_share = (
            cd["total_billing"] / state_total_billing * 100
            if state_total_billing > 0
            else 0.0
        )
        # Sort providers by risk score descending
        cd["providers"].sort(key=lambda x: x["risk_score"], reverse=True)

        cities.append({
            "city": city_name,
            "provider_count": cd["provider_count"],
            "total_billing": round(cd["total_billing"], 2),
            "total_claims": cd["total_claims"],
            "billing_share_pct": round(billing_share, 1),
            "top_providers": cd["providers"][:10],  # Top 10 by risk
        })

    return {
        "state": state,
        "medicaid_enrollment": state_enrollment,
        "total_billing": round(state_total_billing, 2),
        "provider_count": state_provider_count,
        "billing_per_enrollee": round(
            state_total_billing / state_enrollment if state_enrollment > 0 else 0, 2
        ),
        "cities": cities,
    }


@router.post("/enrollment/refresh")
async def refresh_enrollment():
    """Force-refresh enrollment data from CMS API."""
    data = await fetch_enrollment_data()
    set_enrollment(data)
    return {"ok": True, "states_loaded": len(data)}
