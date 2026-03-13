"""
DME (Durable Medical Equipment) Fraud Analyzer.

Detects DME-related fraud patterns using HCPCS E/K/L codes from the
in-memory prescan cache.

Signals:
  - High-cost DME concentration (wheelchairs, oxygen, prosthetics)
  - Unusual DME volume vs. peer average
  - DME without supporting E&M visit codes
  - Rental vs. purchase anomalies

Performance: all analyses run from the in-memory prescan cache — no Parquet
queries needed.
"""
import logging
import statistics
import time as _time
from typing import Any

from core.store import get_prescanned, get_provider_by_npi

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

log = logging.getLogger(__name__)

# ── Reference data ───────────────────────────────────────────────────────────
DME_PREFIXES = ("E", "K", "L")

HIGH_COST_DME = {
    "E1390", "E0431", "E0260", "E0601", "E1161", "E1235", "E1238",
    "E0470", "E0471", "K0823", "K0856", "K0861", "K0869",
    "L5301", "L5321", "L1843", "L3000",
}

TYPICALLY_RENTED = {
    "E1390", "E0260", "E0601", "E0470", "E0471", "E1161", "K0823",
}

EM_PREFIXES = ("992", "993", "994", "995")


def _is_dme_code(code: str) -> bool:
    return code.upper().startswith(DME_PREFIXES)


def _is_em_code(code: str) -> bool:
    return any(code.startswith(p) for p in EM_PREFIXES)


async def analyze_provider(npi: str) -> dict:
    """Full DME analysis for a single provider."""
    p = get_provider_by_npi(npi)
    if not p:
        return {"npi": npi, "available": False, "note": "Provider not found", "signals": []}

    hcpcs_list = p.get("hcpcs") or []
    total_paid = p.get("total_paid") or 0

    dme_rows = [h for h in hcpcs_list if _is_dme_code(h.get("hcpcs_code", ""))]
    em_rows = [h for h in hcpcs_list if _is_em_code(h.get("hcpcs_code", ""))]

    dme_total_paid = sum(h.get("total_paid", 0) or 0 for h in dme_rows)
    dme_pct = (dme_total_paid / total_paid * 100) if total_paid > 0 else 0
    em_claims = sum(h.get("total_claims", 0) or 0 for h in em_rows)
    dme_claims = sum(h.get("total_claims", 0) or 0 for h in dme_rows)

    # Compute peer stats for DME volume
    all_providers = get_prescanned()
    dme_paid_values = []
    for pp in all_providers:
        pp_dme = sum(
            h.get("total_paid", 0) or 0
            for h in (pp.get("hcpcs") or [])
            if _is_dme_code(h.get("hcpcs_code", ""))
        )
        if pp_dme > 0:
            dme_paid_values.append(pp_dme)

    avg_peer = statistics.mean(dme_paid_values) if dme_paid_values else 0
    std_peer = statistics.stdev(dme_paid_values) if len(dme_paid_values) > 1 else 1
    median_peer = statistics.median(dme_paid_values) if dme_paid_values else 0

    signals = []

    # Signal 1: High-cost DME concentration
    high_cost_paid = sum(
        h.get("total_paid", 0) or 0 for h in dme_rows
        if h.get("hcpcs_code", "").upper() in HIGH_COST_DME
    )
    high_cost_pct = (high_cost_paid / total_paid * 100) if total_paid > 0 else 0
    if high_cost_pct > 25:
        signals.append({
            "signal": "high_cost_dme_concentration",
            "score": min(high_cost_pct / 70, 1.0),
            "severity": "HIGH" if high_cost_pct > 50 else "MEDIUM",
            "description": f"{high_cost_pct:.1f}% of billing from high-cost DME items",
            "detail": {
                "high_cost_paid": round(high_cost_paid, 2),
                "pct": round(high_cost_pct, 1),
                "codes": [h["hcpcs_code"] for h in dme_rows if h.get("hcpcs_code", "").upper() in HIGH_COST_DME],
            },
        })

    # Signal 2: Unusual DME volume vs peers
    if avg_peer > 0 and dme_total_paid > 0:
        z_score = (dme_total_paid - avg_peer) / max(std_peer, 1)
        if z_score > 2:
            multiple = dme_total_paid / avg_peer
            signals.append({
                "signal": "unusual_dme_volume",
                "score": min(z_score / 5, 1.0),
                "severity": "HIGH" if z_score > 3 else "MEDIUM",
                "description": f"DME billing {multiple:.1f}x peer average (z-score {z_score:.1f})",
                "detail": {
                    "provider_dme_paid": round(dme_total_paid, 2),
                    "peer_avg": round(avg_peer, 2),
                    "peer_median": round(median_peer, 2),
                    "z_score": round(z_score, 2),
                    "multiple": round(multiple, 1),
                    "peer_count": len(dme_paid_values),
                },
            })

    # Signal 3: DME without supporting E&M codes
    if dme_claims > 10 and em_claims == 0:
        signals.append({
            "signal": "dme_without_em",
            "score": 0.8,
            "severity": "HIGH",
            "description": f"{dme_claims} DME claims with no E&M visit codes on file",
            "detail": {
                "dme_claims": dme_claims,
                "em_claims": em_claims,
                "note": "DME suppliers should have supporting E&M visit documentation",
            },
        })
    elif dme_claims > 10 and em_claims > 0:
        ratio = dme_claims / em_claims
        if ratio > 5:
            signals.append({
                "signal": "dme_em_ratio_imbalance",
                "score": min(ratio / 15, 1.0),
                "severity": "MEDIUM",
                "description": f"DME-to-E&M ratio of {ratio:.1f}:1 (expected < 5:1)",
                "detail": {
                    "dme_claims": dme_claims,
                    "em_claims": em_claims,
                    "ratio": round(ratio, 1),
                },
            })

    # Signal 4: Rental item concentration
    rental_items = [h for h in dme_rows if h.get("hcpcs_code", "").upper() in TYPICALLY_RENTED]
    rental_paid = sum(h.get("total_paid", 0) or 0 for h in rental_items)
    rental_pct = (rental_paid / total_paid * 100) if total_paid > 0 else 0
    if rental_pct > 30 and len(rental_items) >= 2:
        signals.append({
            "signal": "rental_item_concentration",
            "score": min(rental_pct / 60, 1.0),
            "severity": "MEDIUM",
            "description": f"{rental_pct:.1f}% of billing from typically-rented DME items",
            "detail": {
                "rental_paid": round(rental_paid, 2),
                "pct": round(rental_pct, 1),
                "codes": [h["hcpcs_code"] for h in rental_items],
                "note": "High concentration of rental items may indicate purchase-vs-rent abuse",
            },
        })

    composite = 0.0
    if signals:
        composite = min(sum(s["score"] for s in signals) / len(signals) * 100, 100)

    return {
        "npi": npi,
        "available": True,
        "dme_billing_total": round(dme_total_paid, 2),
        "dme_billing_pct": round(dme_pct, 1),
        "total_paid": round(total_paid, 2),
        "dme_codes_used": len(dme_rows),
        "em_claims": em_claims,
        "top_dme_codes": [
            {
                "code": h.get("hcpcs_code", ""),
                "total_paid": round(h.get("total_paid", 0) or 0, 2),
                "total_claims": h.get("total_claims", 0) or 0,
                "is_high_cost": h.get("hcpcs_code", "").upper() in HIGH_COST_DME,
                "is_rental_type": h.get("hcpcs_code", "").upper() in TYPICALLY_RENTED,
            }
            for h in dme_rows[:15]
        ],
        "peer_comparison": {
            "avg_dme_paid": round(avg_peer, 2),
            "median_dme_paid": round(median_peer, 2),
            "peer_count": len(dme_paid_values),
        },
        "signals": signals,
        "composite_risk": round(composite, 1),
    }


async def get_high_risk_providers(limit: int = 50) -> dict:
    """Find providers with the highest DME fraud risk indicators."""
    cached = _cache_get(f"dme_high_risk:{limit}")
    if cached is not None:
        return cached
    providers = get_prescanned()
    if not providers:
        return {"available": True, "providers": [], "total": 0, "kpis": _empty_kpis()}

    # Single pass: compute DME stats for all providers
    all_dme_paid = []
    provider_data = []

    for p in providers:
        npi = p["npi"]
        total_paid = p.get("total_paid") or 0
        hcpcs_list = p.get("hcpcs") or []

        dme_paid = 0
        dme_claims = 0
        dme_code_count = 0
        high_cost_paid = 0
        em_claims = 0
        rental_paid = 0

        for h in hcpcs_list:
            code = h.get("hcpcs_code", "").upper()
            paid = h.get("total_paid", 0) or 0
            claims = h.get("total_claims", 0) or 0

            if code.startswith(DME_PREFIXES):
                dme_paid += paid
                dme_claims += claims
                dme_code_count += 1
                if code in HIGH_COST_DME:
                    high_cost_paid += paid
                if code in TYPICALLY_RENTED:
                    rental_paid += paid
            if _is_em_code(code):
                em_claims += claims

        if dme_paid > 0:
            all_dme_paid.append(dme_paid)

        if dme_paid <= 0 or total_paid <= 0:
            continue

        dme_pct = dme_paid / total_paid * 100
        if dme_pct < 10:
            continue

        provider_data.append({
            "npi": npi,
            "provider_name": p.get("provider_name", ""),
            "state": p.get("state", ""),
            "total_paid": total_paid,
            "dme_paid": dme_paid,
            "dme_pct": dme_pct,
            "dme_code_count": dme_code_count,
            "high_cost_paid": high_cost_paid,
            "dme_claims": dme_claims,
            "em_claims": em_claims,
            "rental_paid": rental_paid,
            "total_benes": p.get("total_beneficiaries") or 0,
            "risk_score": p.get("risk_score", 0),
        })

    # Compute peer stats
    avg_dme = statistics.mean(all_dme_paid) if all_dme_paid else 0
    std_dme = statistics.stdev(all_dme_paid) if len(all_dme_paid) > 1 else 1

    result = []
    for r in provider_data:
        high_cost_pct = (r["high_cost_paid"] / r["total_paid"] * 100) if r["total_paid"] > 0 else 0
        rental_pct = (r["rental_paid"] / r["total_paid"] * 100) if r["total_paid"] > 0 else 0
        z_score = (r["dme_paid"] - avg_dme) / max(std_dme, 1) if avg_dme > 0 else 0

        flags = []
        if high_cost_pct > 25:
            flags.append("High-cost DME concentration")
        if z_score > 2:
            flags.append("Unusual DME volume")
        if r["dme_claims"] > 10 and r["em_claims"] == 0:
            flags.append("DME without E&M visits")
        elif r["dme_claims"] > 10 and r["em_claims"] > 0 and r["dme_claims"] / r["em_claims"] > 5:
            flags.append("DME/E&M ratio imbalance")
        if rental_pct > 30:
            flags.append("Rental item concentration")

        risk = 0
        if flags:
            risk = min(len(flags) * 25 + r["dme_pct"] * 0.5, 100)

        result.append({
            "npi": r["npi"],
            "provider_name": r["provider_name"],
            "state": r["state"],
            "total_paid": round(r["total_paid"], 2),
            "dme_paid": round(r["dme_paid"], 2),
            "dme_pct": round(r["dme_pct"], 1),
            "dme_code_count": r["dme_code_count"],
            "high_cost_pct": round(high_cost_pct, 1),
            "dme_claims": r["dme_claims"],
            "em_claims": r["em_claims"],
            "rental_pct": round(rental_pct, 1),
            "z_score": round(z_score, 2),
            "total_benes": r["total_benes"],
            "flags": flags,
            "flag_count": len(flags),
            "dme_risk": round(risk, 1),
            "risk_score": r["risk_score"],
        })

    result.sort(key=lambda x: x["dme_risk"], reverse=True)
    result = result[:limit]

    response = {
        "available": True,
        "providers": result,
        "total": len(result),
        "kpis": {
            "total_dme_providers": len(result),
            "total_dme_billing": round(sum(r["dme_paid"] for r in result), 2),
            "avg_dme_pct": round(
                sum(r["dme_pct"] for r in result) / max(len(result), 1), 1
            ),
            "flagged_count": sum(1 for r in result if r["flag_count"] > 0),
            "high_cost_count": sum(1 for r in result if r["high_cost_pct"] > 25),
            "no_em_count": sum(
                1 for r in result if r["dme_claims"] > 10 and r["em_claims"] == 0
            ),
        },
    }
    _cache_set(f"dme_high_risk:{limit}", response)
    return response


def _empty_kpis() -> dict:
    return {
        "total_dme_providers": 0,
        "total_dme_billing": 0,
        "avg_dme_pct": 0,
        "flagged_count": 0,
        "high_cost_count": 0,
        "no_em_count": 0,
    }
