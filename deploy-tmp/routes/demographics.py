"""
Demographics API — overlay Census poverty/population data with provider billing
to create a demographic fraud risk layer.
"""

from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends

from core.census_store import (
    get_state_demographics,
    get_all_demographics,
    compute_demographic_risk,
)
from core.store import get_prescanned

from routes.auth import require_user

router = APIRouter(prefix="/api/demographics", tags=["demographics"], dependencies=[Depends(require_user)])


def _build_state_overlay() -> dict[str, dict]:
    """
    Merge provider billing data (from prescan cache) with Census demographics
    for every state that has demographic data.
    Returns a dict keyed by state abbreviation.
    """
    providers = get_prescanned()

    # Aggregate provider stats per state
    state_agg: dict[str, dict] = defaultdict(lambda: {
        "provider_count": 0,
        "total_paid": 0.0,
        "total_claims": 0,
        "total_beneficiaries": 0,
        "risk_scores": [],
    })

    for p in providers:
        st = (p.get("state") or "").upper().strip()
        if not st:
            continue
        agg = state_agg[st]
        agg["provider_count"] += 1
        agg["total_paid"] += float(p.get("total_paid") or 0)
        agg["total_claims"] += int(p.get("total_claims") or 0)
        agg["total_beneficiaries"] += int(p.get("total_beneficiaries") or 0)
        score = p.get("risk_score")
        if score is not None:
            agg["risk_scores"].append(float(score))

    # Build overlay for all states with demographics
    all_demo = get_all_demographics()
    result: dict[str, dict] = {}

    for st, demo in all_demo.items():
        agg = state_agg.get(st, {
            "provider_count": 0,
            "total_paid": 0.0,
            "total_claims": 0,
            "total_beneficiaries": 0,
            "risk_scores": [],
        })

        scores = agg["risk_scores"] if isinstance(agg.get("risk_scores"), list) else []
        avg_risk = round(sum(scores) / len(scores), 1) if scores else 0.0

        pop = demo.get("population", 1)
        billing_per_capita = agg["total_paid"] / pop if pop > 0 else 0.0

        demo_risk = compute_demographic_risk(st, billing_per_capita)

        result[st] = {
            **demo,
            "provider_count": agg["provider_count"],
            "total_paid": round(agg["total_paid"], 2),
            "total_claims": agg["total_claims"],
            "total_beneficiaries": agg["total_beneficiaries"],
            "avg_risk_score": avg_risk,
            "billing_per_capita": round(billing_per_capita, 2),
            "demographic_risk_score": demo_risk,
        }

    return result


@router.get("/risk-map")
async def risk_map():
    """
    All states with demographic data + provider billing overlay
    + composite demographic risk score.
    """
    overlay = _build_state_overlay()
    states_list = sorted(overlay.values(), key=lambda s: s["demographic_risk_score"], reverse=True)

    # Summary KPIs
    elevated = sum(1 for s in states_list if s["demographic_risk_score"] >= 60)
    all_scores = [s["demographic_risk_score"] for s in states_list]
    national_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    # Determine highest correlation factor
    # Check which demographic factor has highest correlation with avg_risk_score
    factors = {
        "Poverty Rate": "poverty_rate",
        "Medicaid %": "medicaid_pct",
        "Low Income": "median_income",
        "Uninsured %": "pct_uninsured",
    }
    best_factor = "Poverty Rate"
    best_corr = 0.0

    states_with_risk = [s for s in states_list if s["avg_risk_score"] > 0]
    if len(states_with_risk) >= 3:
        for label, key in factors.items():
            xs = [s[key] for s in states_with_risk]
            ys = [s["avg_risk_score"] for s in states_with_risk]
            # Invert income so higher value = higher risk
            if key == "median_income":
                xs = [-x for x in xs]
            corr = _pearson(xs, ys)
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_factor = label

    return {
        "states": states_list,
        "kpis": {
            "states_elevated_risk": elevated,
            "highest_correlation_factor": best_factor,
            "correlation_value": round(best_corr, 3),
            "national_avg_demographic_risk": national_avg,
        },
    }


@router.get("/correlations")
async def correlations():
    """
    Scatter plot data: x=poverty_rate, y=avg_risk_score per state.
    Only includes states that have at least one scanned provider.
    """
    overlay = _build_state_overlay()
    points = []
    for st, data in overlay.items():
        if data["provider_count"] > 0:
            points.append({
                "state": st,
                "poverty_rate": data["poverty_rate"],
                "avg_risk_score": data["avg_risk_score"],
                "provider_count": data["provider_count"],
                "median_income": data["median_income"],
                "medicaid_pct": data["medicaid_pct"],
                "demographic_risk_score": data["demographic_risk_score"],
            })

    # Sort by poverty_rate for clean scatter
    points.sort(key=lambda p: p["poverty_rate"])

    return {"correlations": points}


@router.get("/state/{state}")
async def state_detail(state: str):
    """
    Detailed demographic + billing breakdown for a single state.
    Includes per-provider list for that state.
    """
    st = state.upper().strip()
    demo = get_state_demographics(st)
    if demo is None:
        raise HTTPException(404, f"No demographic data for state: {state}")

    providers = get_prescanned()
    state_providers = [
        {
            "npi": p.get("npi"),
            "provider_name": p.get("provider_name", ""),
            "city": p.get("city", ""),
            "total_paid": p.get("total_paid", 0),
            "total_claims": p.get("total_claims", 0),
            "risk_score": p.get("risk_score", 0),
            "flag_count": len(p.get("flags") or []),
        }
        for p in providers
        if (p.get("state") or "").upper().strip() == st
    ]

    # Sort by risk score desc
    state_providers.sort(key=lambda p: p["risk_score"], reverse=True)

    total_paid = sum(p["total_paid"] for p in state_providers)
    total_claims = sum(p["total_claims"] for p in state_providers)
    avg_risk = round(
        sum(p["risk_score"] for p in state_providers) / len(state_providers), 1
    ) if state_providers else 0.0

    pop = demo.get("population", 1)
    billing_per_capita = total_paid / pop if pop > 0 else 0.0
    demo_risk = compute_demographic_risk(st, billing_per_capita)

    return {
        **demo,
        "provider_count": len(state_providers),
        "total_paid": round(total_paid, 2),
        "total_claims": total_claims,
        "avg_risk_score": avg_risk,
        "billing_per_capita": round(billing_per_capita, 2),
        "demographic_risk_score": demo_risk,
        "providers": state_providers[:100],  # cap at 100 for response size
        "providers_total": len(state_providers),
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Simple Pearson correlation coefficient."""
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)
