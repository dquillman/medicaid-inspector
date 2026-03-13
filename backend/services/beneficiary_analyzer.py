"""
Beneficiary-level fraud detection — uses in-memory prescan cache to surface
provider-level patterns that indicate beneficiary fraud:

1. Doctor shopping proxy: providers whose HCPCS codes overlap heavily with
   many other providers (high code-sharing indicates beneficiaries seeing
   multiple providers for the same services).
2. High utilization: providers with abnormally high claims-per-beneficiary
   and revenue-per-beneficiary vs. peers.
3. Geographic impossibility proxy: providers with NPPES data showing
   multi-state billing or distant servicing locations.
4. Excessive services: providers whose service counts per beneficiary
   far exceed peer medians.

Performance: all analyses run from the in-memory prescan cache — no Parquet
queries needed.
"""
import logging
import statistics
import time as _time
from collections import defaultdict
from typing import Any

from core.store import get_prescanned, get_provider_by_npi

log = logging.getLogger(__name__)

# ── In-memory result cache (TTL 10 minutes) ──────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 600


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (_time.time(), value)


# ── Helper: aggregate provider stats from cache ──────────────────────────────

def _build_provider_aggs() -> list[dict]:
    """Build per-provider aggregate stats from cache."""
    providers = get_prescanned()
    if not providers:
        return []

    result = []
    for p in providers:
        total_paid = p.get("total_paid") or 0
        total_claims = p.get("total_claims") or 0
        total_benes = p.get("total_beneficiaries") or 0
        distinct_hcpcs = p.get("distinct_hcpcs") or 0
        active_months = p.get("active_months") or 0
        claims_per_bene = (total_claims / total_benes) if total_benes > 0 else 0
        rev_per_bene = (total_paid / total_benes) if total_benes > 0 else 0

        result.append({
            "npi": p["npi"],
            "total_paid": total_paid,
            "total_claims": total_claims,
            "total_benes": total_benes,
            "distinct_hcpcs": distinct_hcpcs,
            "active_months": active_months,
            "claims_per_bene": claims_per_bene,
            "rev_per_bene": rev_per_bene,
        })
    return result


# ── Doctor Shopping Proxy ───────────────────────────────────────────────────

async def detect_doctor_shopping(limit: int = 100) -> dict:
    """
    Find providers whose HCPCS codes overlap with many other providers and who
    have high claims-per-beneficiary — proxy for beneficiary doctor shopping.
    """
    cached = _cache_get(f"doctor_shopping:{limit}")
    if cached is not None:
        return cached
    providers = get_prescanned()
    if not providers:
        return {"flagged": [], "total_flagged": 0, "note": "No providers in cache"}

    # Build code popularity: how many NPIs bill each HCPCS code
    code_npi_count: dict[str, int] = defaultdict(int)
    npi_codes: dict[str, list[dict]] = {}

    for p in providers:
        npi = p["npi"]
        hcpcs_list = p.get("hcpcs") or []
        codes_for_npi = []
        for h in hcpcs_list:
            code = h.get("hcpcs_code", "")
            if code:
                code_npi_count[code] += 1
                codes_for_npi.append({
                    "code": code,
                    "paid": h.get("total_paid", 0) or 0,
                    "claims": h.get("total_claims", 0) or 0,
                })
        npi_codes[npi] = codes_for_npi

    # Score each provider
    scored = []
    for p in providers:
        npi = p["npi"]
        total_benes = p.get("total_beneficiaries") or 0
        total_claims = p.get("total_claims") or 0
        total_paid = p.get("total_paid") or 0
        if total_benes <= 0:
            continue

        claims_per_bene = total_claims / total_benes
        codes = npi_codes.get(npi, [])

        # Count how many of this provider's codes are shared with 10+ other NPIs
        shared_codes = [c for c in codes if code_npi_count.get(c["code"], 0) >= 10]
        if not shared_codes:
            continue

        competing_counts = [code_npi_count[c["code"]] for c in shared_codes]
        avg_competing = sum(competing_counts) / len(competing_counts) if competing_counts else 0
        max_competing = max(competing_counts) if competing_counts else 0
        shopping_score = claims_per_bene * avg_competing

        scored.append({
            "npi": npi,
            "shared_code_count": len(shared_codes),
            "max_competing_providers": max_competing,
            "avg_competing_providers": round(avg_competing, 1),
            "total_paid": round(total_paid, 2),
            "total_claims": total_claims,
            "total_benes": total_benes,
            "claims_per_bene": round(claims_per_bene, 2),
            "shopping_score": round(shopping_score, 2),
        })

    scored.sort(key=lambda x: x["shopping_score"], reverse=True)
    flagged = scored[:limit]

    result = {
        "flagged": flagged,
        "total_flagged": len(flagged),
        "note": "Providers whose patients likely see many other providers for the same services"
    }
    _cache_set(f"doctor_shopping:{limit}", result)
    return result


# ── High Utilization ────────────────────────────────────────────────────────

async def detect_high_utilization(limit: int = 100) -> dict:
    """
    Find providers where beneficiaries have abnormally high utilization:
    claims-per-beneficiary and revenue-per-beneficiary far exceeding peers.
    """
    cached = _cache_get(f"high_utilization:{limit}")
    if cached is not None:
        return cached
    aggs = _build_provider_aggs()
    if not aggs:
        return {"flagged": [], "total_flagged": 0, "note": "No providers in cache"}

    valid = [a for a in aggs if a["total_benes"] > 0]
    if not valid:
        return {"flagged": [], "total_flagged": 0, "note": "No providers with beneficiaries"}

    cpb_values = [a["claims_per_bene"] for a in valid]
    rpb_values = [a["rev_per_bene"] for a in valid]

    mean_cpb = statistics.mean(cpb_values)
    std_cpb = statistics.stdev(cpb_values) if len(cpb_values) > 1 else 1
    mean_rpb = statistics.mean(rpb_values)
    std_rpb = statistics.stdev(rpb_values) if len(rpb_values) > 1 else 1
    median_cpb = statistics.median(cpb_values)
    median_rpb = statistics.median(rpb_values)
    p90_cpb = sorted(cpb_values)[int(len(cpb_values) * 0.9)]
    p90_rpb = sorted(rpb_values)[int(len(rpb_values) * 0.9)]

    flagged = []
    for a in valid:
        if a["claims_per_bene"] <= p90_cpb and a["rev_per_bene"] <= p90_rpb:
            continue
        cpb_z = (a["claims_per_bene"] - mean_cpb) / std_cpb if std_cpb else 0
        rpb_z = (a["rev_per_bene"] - mean_rpb) / std_rpb if std_rpb else 0
        flagged.append({
            **a,
            "claims_per_bene": round(a["claims_per_bene"], 2),
            "rev_per_bene": round(a["rev_per_bene"], 2),
            "cpb_z_score": round(cpb_z, 2),
            "rpb_z_score": round(rpb_z, 2),
            "peer_median_cpb": round(median_cpb, 2),
            "peer_p90_cpb": round(p90_cpb, 2),
            "peer_median_rpb": round(median_rpb, 2),
            "peer_p90_rpb": round(p90_rpb, 2),
        })

    flagged.sort(key=lambda x: x.get("cpb_z_score", 0) + x.get("rpb_z_score", 0), reverse=True)
    flagged = flagged[:limit]

    result = {
        "flagged": flagged,
        "total_flagged": len(flagged),
        "note": "Providers whose beneficiaries have abnormally high claims/revenue per beneficiary"
    }
    _cache_set(f"high_utilization:{limit}", result)
    return result


# ── Geographic Impossibility Proxy ──────────────────────────────────────────

async def detect_geographic_anomalies(limit: int = 100) -> dict:
    """
    Detect providers with NPPES data suggesting multi-state operations or
    mismatched billing/practice locations.
    """
    cached = _cache_get(f"geographic:{limit}")
    if cached is not None:
        return cached
    providers = get_prescanned()
    if not providers:
        return {"flagged": [], "total_flagged": 0, "note": "No providers in cache"}

    flagged = []
    for p in providers:
        npi = p["npi"]
        nppes = p.get("nppes") or {}
        state = p.get("state") or ""
        addr = nppes.get("address") or {}
        nppes_state = addr.get("state", "")

        # Check for state mismatch between billing data and NPPES
        timeline = p.get("timeline") or []
        states_in_data = set()
        if state:
            states_in_data.add(state)
        if nppes_state and nppes_state != state:
            states_in_data.add(nppes_state)

        # Look at HCPCS diversity as proxy for multi-location billing
        hcpcs_list = p.get("hcpcs") or []
        distinct_codes = len(hcpcs_list)
        total_paid = p.get("total_paid") or 0
        total_claims = p.get("total_claims") or 0
        total_benes = p.get("total_beneficiaries") or 0
        active_months = p.get("active_months") or 0

        # Flag if state mismatch or very high code diversity suggesting multi-location
        state_count = len(states_in_data)
        if state_count >= 2 or (distinct_codes > 50 and active_months >= 10):
            geo_risk = state_count * 10 + distinct_codes * 0.5
            flagged.append({
                "npi": npi,
                "state_count": state_count,
                "states": list(states_in_data),
                "total_paid": round(total_paid, 2),
                "total_claims": total_claims,
                "total_benes": total_benes,
                "distinct_hcpcs": distinct_codes,
                "active_months": active_months,
                "geo_risk_score": round(geo_risk, 1),
            })

    flagged.sort(key=lambda x: x["geo_risk_score"], reverse=True)
    flagged = flagged[:limit]

    result = {
        "flagged": flagged,
        "total_flagged": len(flagged),
        "note": "Providers with geographic anomalies — possible multi-state billing"
    }
    _cache_set(f"geographic:{limit}", result)
    return result


# ── Excessive Services ──────────────────────────────────────────────────────

async def detect_excessive_services(limit: int = 100) -> dict:
    """
    Find providers with abnormally high total claims per beneficiary
    vs. peer median.
    """
    cached = _cache_get(f"excessive:{limit}")
    if cached is not None:
        return cached
    aggs = _build_provider_aggs()
    if not aggs:
        return {"flagged": [], "total_flagged": 0, "note": "No providers in cache"}

    valid = [a for a in aggs if a["total_benes"] > 0]
    if not valid:
        return {"flagged": [], "total_flagged": 0, "note": "No providers with beneficiaries"}

    spb_values = [a["claims_per_bene"] for a in valid]
    mean_spb = statistics.mean(spb_values)
    std_spb = statistics.stdev(spb_values) if len(spb_values) > 1 else 1
    median_spb = statistics.median(spb_values)
    p90_spb = sorted(spb_values)[int(len(spb_values) * 0.9)]
    p95_spb = sorted(spb_values)[int(len(spb_values) * 0.95)]

    flagged = []
    for a in valid:
        if a["claims_per_bene"] <= p90_spb:
            continue
        z_score = (a["claims_per_bene"] - mean_spb) / std_spb if std_spb else 0
        multiple = a["claims_per_bene"] / median_spb if median_spb > 0 else 0
        flagged.append({
            "npi": a["npi"],
            "total_services": a["total_claims"],
            "total_benes": a["total_benes"],
            "total_paid": round(a["total_paid"], 2),
            "distinct_hcpcs": a["distinct_hcpcs"],
            "active_months": a["active_months"],
            "svc_per_bene": round(a["claims_per_bene"], 2),
            "z_score": round(z_score, 2),
            "peer_median": round(median_spb, 2),
            "peer_p90": round(p90_spb, 2),
            "peer_p95": round(p95_spb, 2),
            "multiple_of_median": round(multiple, 2),
        })

    flagged.sort(key=lambda x: x["svc_per_bene"], reverse=True)
    flagged = flagged[:limit]

    result = {
        "flagged": flagged,
        "total_flagged": len(flagged),
        "service_column_used": "TOTAL_CLAIMS",
        "note": "Providers with services-per-beneficiary exceeding the 90th percentile"
    }
    _cache_set(f"excessive:{limit}", result)
    return result


# ── Combined All-In-One ────────────────────────────────────────────────────

async def _run_all_beneficiary_analyses(limit: int = 100) -> dict:
    """Run all 4 detection analyses + summary in a single call."""
    shopping = await detect_doctor_shopping(limit=limit)
    utilization = await detect_high_utilization(limit=limit)
    geographic = await detect_geographic_anomalies(limit=limit)
    excessive = await detect_excessive_services(limit=limit)

    providers = get_prescanned()
    total_providers = len(providers)
    total_bene_records = sum(p.get("total_beneficiaries") or 0 for p in providers)
    total_paid = sum(p.get("total_paid") or 0 for p in providers)

    summary = {
        "total_providers_analyzed": total_providers,
        "total_beneficiary_records": total_bene_records,
        "total_paid": round(total_paid, 2),
        "has_individual_bene_id": False,
        "flagged_counts": {
            "doctor_shopping": shopping.get("total_flagged", 0),
            "high_utilization": utilization.get("total_flagged", 0),
            "geographic_anomalies": geographic.get("total_flagged", 0),
            "excessive_services": excessive.get("total_flagged", 0),
        },
        "note": (
            "Analysis uses aggregate provider data as proxy for beneficiary-level patterns. "
            "Individual BENE_ID column is not present — results are statistical proxies "
            "based on provider aggregates."
        ),
    }

    return {
        "summary": summary,
        "shopping": shopping,
        "utilization": utilization,
        "geographic": geographic,
        "excessive": excessive,
    }


# ── Summary ─────────────────────────────────────────────────────────────────

async def beneficiary_fraud_summary() -> dict:
    """High-level summary stats."""
    providers = get_prescanned()
    total_providers = len(providers)
    total_bene_records = sum(p.get("total_beneficiaries") or 0 for p in providers)
    total_paid = sum(p.get("total_paid") or 0 for p in providers)
    total_claims = sum(p.get("total_claims") or 0 for p in providers)

    # Run detections with small limits for counts
    shopping = await detect_doctor_shopping(limit=200)
    utilization = await detect_high_utilization(limit=200)
    geographic = await detect_geographic_anomalies(limit=200)
    excessive = await detect_excessive_services(limit=200)

    return {
        "total_providers_analyzed": total_providers,
        "total_beneficiary_records": total_bene_records,
        "total_paid": round(total_paid, 2),
        "has_individual_bene_id": False,
        "flagged_counts": {
            "doctor_shopping": shopping.get("total_flagged", 0),
            "high_utilization": utilization.get("total_flagged", 0),
            "geographic_anomalies": geographic.get("total_flagged", 0),
            "excessive_services": excessive.get("total_flagged", 0),
        },
        "note": (
            "Analysis uses aggregate provider data as proxy for beneficiary-level patterns. "
            "Individual BENE_ID column is not present — results are statistical proxies "
            "based on provider aggregates."
        ),
    }


# ── Provider-Specific Beneficiary Fraud ─────────────────────────────────────

async def provider_beneficiary_fraud(npi: str) -> dict:
    """Analyze beneficiary fraud patterns for a specific provider."""
    p = get_provider_by_npi(npi)
    if not p:
        return {"npi": npi, "found": False, "note": "Provider not found in cache"}

    total_paid = p.get("total_paid") or 0
    total_claims = p.get("total_claims") or 0
    total_benes = p.get("total_beneficiaries") or 0
    distinct_hcpcs = p.get("distinct_hcpcs") or 0
    active_months = p.get("active_months") or 0
    cpb = (total_claims / total_benes) if total_benes > 0 else 0
    rpb = (total_paid / total_benes) if total_benes > 0 else 0

    # Compute peer stats
    aggs = _build_provider_aggs()
    valid = [a for a in aggs if a["total_benes"] > 0]

    cpb_values = [a["claims_per_bene"] for a in valid]
    rpb_values = [a["rev_per_bene"] for a in valid]

    peers = {}
    if cpb_values:
        peers["mean_cpb"] = round(statistics.mean(cpb_values), 2)
        peers["median_cpb"] = round(statistics.median(cpb_values), 2)
        sorted_cpb = sorted(cpb_values)
        peers["p90_cpb"] = round(sorted_cpb[int(len(sorted_cpb) * 0.9)], 2)
    if rpb_values:
        peers["mean_rpb"] = round(statistics.mean(rpb_values), 2)
        peers["median_rpb"] = round(statistics.median(rpb_values), 2)
        sorted_rpb = sorted(rpb_values)
        peers["p90_rpb"] = round(sorted_rpb[int(len(sorted_rpb) * 0.9)], 2)
    peers["peer_count"] = len(valid)

    # Code overlap from cache
    hcpcs_list = p.get("hcpcs") or []
    providers = get_prescanned()
    code_npi_count: dict[str, int] = defaultdict(int)
    for prov in providers:
        for h in (prov.get("hcpcs") or []):
            code = h.get("hcpcs_code", "")
            if code:
                code_npi_count[code] += 1

    code_overlap = []
    for h in hcpcs_list[:10]:
        code = h.get("hcpcs_code", "")
        if code:
            code_overlap.append({
                "hcpcs_code": code,
                "other_providers": code_npi_count.get(code, 1) - 1,
            })
    code_overlap.sort(key=lambda x: x["other_providers"], reverse=True)

    # Flags
    flags = []
    p90_cpb = peers.get("p90_cpb", 0)
    p90_rpb = peers.get("p90_rpb", 0)
    if p90_cpb and cpb > p90_cpb:
        flags.append({
            "type": "high_utilization",
            "severity": "HIGH",
            "description": f"Claims/beneficiary ({cpb:.1f}) exceeds 90th percentile ({p90_cpb:.1f})"
        })
    if p90_rpb and rpb > p90_rpb:
        flags.append({
            "type": "excessive_revenue",
            "severity": "HIGH",
            "description": f"Revenue/beneficiary (${rpb:,.0f}) exceeds 90th percentile (${p90_rpb:,.0f})"
        })
    if code_overlap and code_overlap[0].get("other_providers", 0) > 50:
        flags.append({
            "type": "doctor_shopping_risk",
            "severity": "MEDIUM",
            "description": f"Top code shared with {code_overlap[0]['other_providers']} other providers"
        })

    return {
        "npi": npi,
        "found": True,
        "provider_stats": {
            "total_paid": round(total_paid, 2),
            "total_claims": total_claims,
            "total_benes": total_benes,
            "distinct_hcpcs": distinct_hcpcs,
            "active_months": active_months,
            "claims_per_bene": round(cpb, 2),
            "rev_per_bene": round(rpb, 2),
        },
        "peer_comparison": peers,
        "code_overlap": code_overlap[:10],
        "flags": flags,
        "flag_count": len(flags),
    }
