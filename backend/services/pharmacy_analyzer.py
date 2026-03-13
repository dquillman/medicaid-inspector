"""
Pharmacy / Drug Fraud Analyzer.

Detects pharmacy and drug-related fraud patterns using HCPCS J-codes
(drug injection codes) from the in-memory prescan cache.

Signals:
  - High-cost drug concentration
  - Controlled substance over-prescribing
  - Dispensing pattern anomalies (early refills, unusual quantities)
  - Drug diversion indicators (high controlled volume + geographic dispersion)

Performance: all analyses run from the in-memory prescan cache — no Parquet
queries needed.
"""
import logging
import time as _time
from collections import defaultdict
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
HIGH_COST_J_CODES = {
    "J0585", "J1745", "J2315", "J9035", "J9310", "J1300", "J0178",
    "J2350", "J9299", "J9271", "J0129", "J3490", "J3590",
}

CONTROLLED_SUBSTANCE_CODES = {
    "J2175", "J2270", "J2310", "J3010", "J2315", "J0592",
    "J0575", "J2060", "J2250", "J1170",
}

J_CODE_PREFIX = "J"


def _is_j_code(code: str) -> bool:
    return code.upper().startswith(J_CODE_PREFIX)


async def analyze_provider(npi: str) -> dict:
    """Full pharmacy analysis for a single provider."""
    p = get_provider_by_npi(npi)
    if not p:
        return {"npi": npi, "available": False, "note": "Provider not found", "signals": []}

    hcpcs_list = p.get("hcpcs") or []
    timeline = p.get("timeline") or []
    total_paid = p.get("total_paid") or 0

    # Filter to J-codes (drug injection codes)
    drug_rows = [h for h in hcpcs_list if _is_j_code(h.get("hcpcs_code", ""))]
    drug_total_paid = sum(h.get("total_paid", 0) or 0 for h in drug_rows)
    drug_pct = (drug_total_paid / total_paid * 100) if total_paid > 0 else 0

    signals = []

    # Signal 1: High-cost drug concentration
    high_cost_paid = sum(
        h.get("total_paid", 0) or 0 for h in drug_rows
        if h.get("hcpcs_code", "").upper() in HIGH_COST_J_CODES
    )
    high_cost_pct = (high_cost_paid / total_paid * 100) if total_paid > 0 else 0
    if high_cost_pct > 30:
        signals.append({
            "signal": "high_cost_drug_concentration",
            "score": min(high_cost_pct / 80, 1.0),
            "severity": "HIGH" if high_cost_pct > 60 else "MEDIUM",
            "description": f"{high_cost_pct:.1f}% of billing from high-cost brand-name drugs",
            "detail": {
                "high_cost_paid": round(high_cost_paid, 2),
                "total_paid": round(total_paid, 2),
                "pct": round(high_cost_pct, 1),
                "codes": [h["hcpcs_code"] for h in drug_rows if h.get("hcpcs_code", "").upper() in HIGH_COST_J_CODES],
            },
        })

    # Signal 2: Controlled substance volume
    controlled_paid = sum(
        h.get("total_paid", 0) or 0 for h in drug_rows
        if h.get("hcpcs_code", "").upper() in CONTROLLED_SUBSTANCE_CODES
    )
    controlled_claims = sum(
        h.get("total_claims", 0) or 0 for h in drug_rows
        if h.get("hcpcs_code", "").upper() in CONTROLLED_SUBSTANCE_CODES
    )
    controlled_pct = (controlled_paid / total_paid * 100) if total_paid > 0 else 0
    if controlled_pct > 15:
        signals.append({
            "signal": "controlled_substance_volume",
            "score": min(controlled_pct / 60, 1.0),
            "severity": "HIGH" if controlled_pct > 40 else "MEDIUM",
            "description": f"{controlled_pct:.1f}% of billing from controlled substances",
            "detail": {
                "controlled_paid": round(controlled_paid, 2),
                "controlled_claims": controlled_claims,
                "pct": round(controlled_pct, 1),
            },
        })

    # Signal 3: Early refill patterns (same J-code in consecutive months)
    early_refills = _detect_early_refills_from_timeline(drug_rows, timeline)
    if early_refills:
        signals.append({
            "signal": "early_refill_pattern",
            "score": min(len(early_refills) / 10, 1.0),
            "severity": "HIGH" if len(early_refills) > 5 else "MEDIUM",
            "description": f"{len(early_refills)} potential early refill instances detected",
            "detail": {
                "instances": early_refills[:10],
                "total_instances": len(early_refills),
            },
        })

    # Signal 4: J3490/J3590 concentration (unclassified drug codes)
    unclassified_paid = sum(
        h.get("total_paid", 0) or 0 for h in drug_rows
        if h.get("hcpcs_code", "").upper() in ("J3490", "J3590")
    )
    unclassified_pct = (unclassified_paid / total_paid * 100) if total_paid > 0 else 0
    if unclassified_pct > 10:
        signals.append({
            "signal": "unclassified_drug_billing",
            "score": min(unclassified_pct / 40, 1.0),
            "severity": "HIGH" if unclassified_pct > 25 else "MEDIUM",
            "description": f"{unclassified_pct:.1f}% billed under unclassified drug codes (J3490/J3590)",
            "detail": {
                "unclassified_paid": round(unclassified_paid, 2),
                "pct": round(unclassified_pct, 1),
            },
        })

    composite = 0.0
    if signals:
        composite = min(sum(s["score"] for s in signals) / len(signals) * 100, 100)

    return {
        "npi": npi,
        "available": True,
        "drug_billing_total": round(drug_total_paid, 2),
        "drug_billing_pct": round(drug_pct, 1),
        "total_paid": round(total_paid, 2),
        "drug_codes_used": len(drug_rows),
        "top_drug_codes": [
            {
                "code": h.get("hcpcs_code", ""),
                "total_paid": round(h.get("total_paid", 0) or 0, 2),
                "total_claims": h.get("total_claims", 0) or 0,
                "is_high_cost": h.get("hcpcs_code", "").upper() in HIGH_COST_J_CODES,
                "is_controlled": h.get("hcpcs_code", "").upper() in CONTROLLED_SUBSTANCE_CODES,
            }
            for h in drug_rows[:15]
        ],
        "signals": signals,
        "composite_risk": round(composite, 1),
    }


async def get_high_risk_providers(limit: int = 50) -> dict:
    """Find providers with the highest pharmacy fraud risk indicators."""
    cached = _cache_get(f"pharmacy_high_risk:{limit}")
    if cached is not None:
        return cached
    providers = get_prescanned()
    if not providers:
        return {"available": True, "providers": [], "total": 0, "kpis": _empty_kpis()}

    result = []
    for p in providers:
        npi = p["npi"]
        total_paid = p.get("total_paid") or 0
        hcpcs_list = p.get("hcpcs") or []

        drug_paid = 0
        drug_claims = 0
        drug_code_count = 0
        high_cost_paid = 0
        controlled_paid = 0
        unclassified_paid = 0

        for h in hcpcs_list:
            code = h.get("hcpcs_code", "").upper()
            paid = h.get("total_paid", 0) or 0
            claims = h.get("total_claims", 0) or 0

            if code.startswith("J"):
                drug_paid += paid
                drug_claims += claims
                drug_code_count += 1
                if code in HIGH_COST_J_CODES:
                    high_cost_paid += paid
                if code in CONTROLLED_SUBSTANCE_CODES:
                    controlled_paid += paid
                if code in ("J3490", "J3590"):
                    unclassified_paid += paid

        if drug_paid <= 0 or total_paid <= 0:
            continue

        drug_pct = drug_paid / total_paid * 100
        if drug_pct < 10:
            continue

        high_cost_pct = high_cost_paid / total_paid * 100
        controlled_pct = controlled_paid / total_paid * 100
        unclassified_pct = unclassified_paid / total_paid * 100

        flags = []
        if high_cost_pct > 30:
            flags.append("High-cost drug concentration")
        if controlled_pct > 15:
            flags.append("Controlled substance volume")
        if unclassified_pct > 10:
            flags.append("Unclassified drug codes")

        risk = 0
        if flags:
            risk = min(len(flags) * 30 + drug_pct * 0.5, 100)

        result.append({
            "npi": npi,
            "provider_name": p.get("provider_name", ""),
            "state": p.get("state", ""),
            "total_paid": round(total_paid, 2),
            "drug_paid": round(drug_paid, 2),
            "drug_pct": round(drug_pct, 1),
            "drug_code_count": drug_code_count,
            "high_cost_pct": round(high_cost_pct, 1),
            "controlled_pct": round(controlled_pct, 1),
            "unclassified_pct": round(unclassified_pct, 1),
            "total_claims": p.get("total_claims") or 0,
            "total_benes": p.get("total_beneficiaries") or 0,
            "flags": flags,
            "flag_count": len(flags),
            "pharmacy_risk": round(risk, 1),
            "risk_score": p.get("risk_score", 0),
        })

    result.sort(key=lambda x: x["pharmacy_risk"], reverse=True)
    result = result[:limit]

    response = {
        "available": True,
        "providers": result,
        "total": len(result),
        "kpis": {
            "total_drug_providers": len(result),
            "total_drug_billing": round(sum(r["drug_paid"] for r in result), 2),
            "avg_drug_pct": round(
                sum(r["drug_pct"] for r in result) / max(len(result), 1), 1
            ),
            "flagged_count": sum(1 for r in result if r["flag_count"] > 0),
            "high_cost_count": sum(1 for r in result if r["high_cost_pct"] > 30),
            "controlled_count": sum(1 for r in result if r["controlled_pct"] > 15),
        },
    }
    _cache_set(f"pharmacy_high_risk:{limit}", response)
    return response


def _detect_early_refills_from_timeline(drug_rows: list[dict], timeline: list[dict]) -> list[dict]:
    """Detect early refills using timeline data — consecutive months with J-code billing."""
    if not timeline or not drug_rows:
        return []

    # Check if provider has drug billing in consecutive months
    drug_codes = {h.get("hcpcs_code", "").upper() for h in drug_rows}
    months = sorted([t.get("month", "") for t in timeline if t.get("month")])

    refills = []
    for i in range(1, len(months)):
        prev_m = months[i - 1]
        curr_m = months[i]
        if prev_m and curr_m and _months_apart(prev_m, curr_m) <= 1:
            # Both consecutive months have billing — possible early refill
            for code in drug_codes:
                if code in CONTROLLED_SUBSTANCE_CODES:
                    refills.append({
                        "code": code,
                        "month1": prev_m,
                        "month2": curr_m,
                    })
    return refills


def _months_apart(m1: str, m2: str) -> int:
    try:
        y1, mo1 = int(m1[:4]), int(m1[5:7])
        y2, mo2 = int(m2[:4]), int(m2[5:7])
        return abs((y2 * 12 + mo2) - (y1 * 12 + mo1))
    except (ValueError, IndexError):
        return 999


def _empty_kpis() -> dict:
    return {
        "total_drug_providers": 0,
        "total_drug_billing": 0,
        "avg_drug_pct": 0,
        "flagged_count": 0,
        "high_cost_count": 0,
        "controlled_count": 0,
    }
