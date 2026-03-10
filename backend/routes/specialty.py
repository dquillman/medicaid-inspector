"""
Specialty Benchmarking — aggregate stats, outlier detection, and per-provider
ranking within their NPPES taxonomy specialty.
"""
import math
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query, Depends
from core.store import get_prescanned
from routes.auth import require_user

router = APIRouter(prefix="/api/specialty", tags=["specialty"], dependencies=[Depends(require_user)])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_specialty(p: dict) -> str:
    """Extract the specialty string from a prescanned provider dict."""
    nppes = p.get("nppes") or {}
    tax = nppes.get("taxonomy") or {}
    desc = (
        tax.get("description")
        or tax.get("desc")
        or p.get("provider_type")
        or p.get("specialty")
        or ""
    ).strip().rstrip(",").strip()
    return desc or "Unknown"


def _get_name(p: dict) -> str:
    nppes = p.get("nppes") or {}
    return nppes.get("name") or p.get("provider_name") or ""


def _get_state(p: dict) -> str:
    return p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state", "")


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the pct-th percentile from an already-sorted list."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _build_specialty_groups() -> dict[str, list[dict]]:
    """Group prescanned providers by specialty."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in get_prescanned():
        spec = _get_specialty(p)
        groups[spec].append(p)
    return groups


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/list")
async def specialty_list():
    """List all specialties with provider counts, sorted by count descending."""
    groups = _build_specialty_groups()
    items = []
    for spec, providers in groups.items():
        total_paid = sum(p.get("total_paid", 0) for p in providers)
        avg_risk = (
            sum(p.get("risk_score", 0) for p in providers) / len(providers)
            if providers else 0
        )
        items.append({
            "specialty": spec,
            "provider_count": len(providers),
            "total_paid": round(total_paid, 2),
            "avg_risk_score": round(avg_risk, 1),
        })
    items.sort(key=lambda x: x["provider_count"], reverse=True)
    return {"specialties": items, "total": len(items)}


@router.get("/{specialty}/stats")
async def specialty_stats(specialty: str):
    """
    Aggregate statistics for a single specialty:
    avg, median, std_dev, percentiles for paid/claims/beneficiaries,
    plus top HCPCS codes.
    """
    groups = _build_specialty_groups()
    providers = groups.get(specialty)
    if not providers:
        raise HTTPException(404, f"No providers found for specialty: {specialty}")

    paid_vals = sorted([p.get("total_paid", 0) for p in providers])
    claims_vals = sorted([p.get("total_claims", 0) for p in providers])
    bene_vals = sorted([p.get("total_beneficiaries", 0) for p in providers])
    n = len(paid_vals)

    avg_paid = sum(paid_vals) / n
    avg_claims = sum(claims_vals) / n
    avg_bene = sum(bene_vals) / n

    # Std dev for paid
    variance = sum((x - avg_paid) ** 2 for x in paid_vals) / n if n > 0 else 0
    std_dev = math.sqrt(variance)

    # HCPCS aggregation from signal_results or flags isn't available in prescan
    # Instead, collect top HCPCS from provider hcpcs data if available
    hcpcs_totals: dict[str, float] = defaultdict(float)
    for p in providers:
        for h in (p.get("hcpcs") or []):
            code = h.get("hcpcs_code") or h.get("code") or ""
            if code:
                hcpcs_totals[code] += h.get("total_paid", 0)

    top_hcpcs = sorted(hcpcs_totals.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "specialty": specialty,
        "provider_count": n,
        "avg_paid_per_provider": round(avg_paid, 2),
        "median_paid": round(_percentile(paid_vals, 50), 2),
        "std_dev": round(std_dev, 2),
        "p25": round(_percentile(paid_vals, 25), 2),
        "p75": round(_percentile(paid_vals, 75), 2),
        "p90": round(_percentile(paid_vals, 90), 2),
        "p95": round(_percentile(paid_vals, 95), 2),
        "avg_claims_per_provider": round(avg_claims, 1),
        "median_claims": round(_percentile(claims_vals, 50), 1),
        "avg_beneficiaries": round(avg_bene, 1),
        "median_beneficiaries": round(_percentile(bene_vals, 50), 1),
        "top_hcpcs": [{"code": code, "total_paid": round(paid, 2)} for code, paid in top_hcpcs],
    }


@router.get("/{specialty}/outliers")
async def specialty_outliers(
    specialty: str,
    limit: int = Query(20, ge=1, le=200),
):
    """
    Providers in this specialty ranked by deviation from the specialty mean (z-score).
    Returns the top outliers.
    """
    groups = _build_specialty_groups()
    providers = groups.get(specialty)
    if not providers:
        raise HTTPException(404, f"No providers found for specialty: {specialty}")

    paid_vals = [p.get("total_paid", 0) for p in providers]
    n = len(paid_vals)
    mean_paid = sum(paid_vals) / n if n else 0
    variance = sum((x - mean_paid) ** 2 for x in paid_vals) / n if n > 1 else 0
    std_dev = math.sqrt(variance) if variance > 0 else 1

    outliers = []
    for p in providers:
        paid = p.get("total_paid", 0)
        z = (paid - mean_paid) / std_dev if std_dev > 0 else 0
        outliers.append({
            "npi": p.get("npi", ""),
            "provider_name": _get_name(p),
            "state": _get_state(p),
            "total_paid": round(paid, 2),
            "total_claims": p.get("total_claims", 0),
            "total_beneficiaries": p.get("total_beneficiaries", 0),
            "risk_score": round(p.get("risk_score", 0), 1),
            "z_score": round(z, 2),
            "deviation_from_mean": round(paid - mean_paid, 2),
        })

    outliers.sort(key=lambda x: x["z_score"], reverse=True)
    return {
        "specialty": specialty,
        "mean_paid": round(mean_paid, 2),
        "std_dev": round(std_dev, 2),
        "provider_count": n,
        "outliers": outliers[:limit],
    }


@router.get("/provider/{npi}/rank")
async def provider_specialty_rank(npi: str):
    """
    Where a specific provider ranks within their specialty.
    Returns percentile for paid, claims, beneficiaries and the specialty stats.
    """
    prescanned = get_prescanned()

    # Find this provider
    target = None
    for p in prescanned:
        if p.get("npi") == npi:
            target = p
            break

    if not target:
        raise HTTPException(404, f"Provider {npi} not found in scanned data")

    specialty = _get_specialty(target)

    # Gather all providers in the same specialty
    peers = [p for p in prescanned if _get_specialty(p) == specialty]
    n = len(peers)
    if n < 2:
        return {
            "npi": npi,
            "specialty": specialty,
            "provider_count": n,
            "note": "Too few providers in this specialty for meaningful comparison",
            "percentiles": None,
            "stats": None,
        }

    target_paid = target.get("total_paid", 0)
    target_claims = target.get("total_claims", 0)
    target_bene = target.get("total_beneficiaries", 0)

    paid_vals = sorted([p.get("total_paid", 0) for p in peers])
    claims_vals = sorted([p.get("total_claims", 0) for p in peers])
    bene_vals = sorted([p.get("total_beneficiaries", 0) for p in peers])

    def calc_percentile_rank(val: float, sorted_list: list[float]) -> float:
        count_below = sum(1 for x in sorted_list if x < val)
        return round((count_below / len(sorted_list)) * 100, 1)

    avg_paid = sum(paid_vals) / n
    avg_claims = sum(claims_vals) / n

    return {
        "npi": npi,
        "specialty": specialty,
        "provider_count": n,
        "this_provider": {
            "total_paid": round(target_paid, 2),
            "total_claims": target_claims,
            "total_beneficiaries": target_bene,
        },
        "percentiles": {
            "total_paid": calc_percentile_rank(target_paid, paid_vals),
            "total_claims": calc_percentile_rank(target_claims, claims_vals),
            "total_beneficiaries": calc_percentile_rank(target_bene, bene_vals),
        },
        "stats": {
            "avg_paid": round(avg_paid, 2),
            "median_paid": round(_percentile(paid_vals, 50), 2),
            "p75_paid": round(_percentile(paid_vals, 75), 2),
            "p90_paid": round(_percentile(paid_vals, 90), 2),
            "p95_paid": round(_percentile(paid_vals, 95), 2),
            "avg_claims": round(avg_claims, 1),
            "median_claims": round(_percentile(claims_vals, 50), 1),
            "p75_claims": round(_percentile(claims_vals, 75), 1),
            "p90_claims": round(_percentile(claims_vals, 90), 1),
            "median_beneficiaries": round(_percentile(bene_vals, 50), 1),
            "p75_beneficiaries": round(_percentile(bene_vals, 75), 1),
            "p90_beneficiaries": round(_percentile(bene_vals, 90), 1),
        },
    }
