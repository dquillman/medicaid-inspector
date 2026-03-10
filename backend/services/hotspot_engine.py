"""
County-level fraud hotspot engine.

Groups providers by 3-digit ZIP prefix and computes a composite
hotspot score (0–100) for each area based on multiple risk dimensions.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.store import get_prescanned
from core.config import settings


# ── Component weights (must sum to 1.0) ──────────────────────────────────────
W_AVG_RISK           = 0.30
W_FLAGGED_PCT        = 0.25
W_BILLING_CONC       = 0.15
W_DENSITY_ANOMALY    = 0.15
W_HIGH_RISK_COUNT    = 0.15

# Severity thresholds
SEV_CRITICAL  = 70
SEV_HIGH      = 50
SEV_ELEVATED  = 30


def _zip3(provider: dict) -> str | None:
    """Extract 3-digit ZIP prefix from NPPES address or fallback fields."""
    nppes = provider.get("nppes") or {}
    addr = nppes.get("address") or {}
    zip_code = addr.get("zip") or ""
    if not zip_code:
        zip_code = provider.get("zip") or ""
    zip_code = str(zip_code).strip().replace("-", "")
    if len(zip_code) >= 3 and zip_code[:3].isdigit():
        return zip_code[:3]
    return None


def _severity(score: float) -> str:
    if score >= SEV_CRITICAL:
        return "CRITICAL"
    if score >= SEV_HIGH:
        return "HIGH"
    if score >= SEV_ELEVATED:
        return "ELEVATED"
    return "NORMAL"


def compute_hotspots() -> list[dict[str, Any]]:
    """
    Build composite hotspot scores for every 3-digit ZIP area that has
    at least one scanned provider with NPPES data.

    Returns a list of hotspot dicts sorted by composite score descending.
    """
    providers = get_prescanned()
    if not providers:
        return []

    # ── Group providers by ZIP3 ───────────────────────────────────────────
    by_zip3: dict[str, list[dict]] = defaultdict(list)
    for p in providers:
        z3 = _zip3(p)
        if z3:
            by_zip3[z3].append(p)

    if not by_zip3:
        return []

    # ── Global reference values (used for density anomaly normalisation) ──
    all_counts = [len(v) for v in by_zip3.values()]
    global_mean_count = sum(all_counts) / len(all_counts) if all_counts else 1.0

    # ── Score each ZIP3 area ──────────────────────────────────────────────
    hotspots: list[dict] = []
    for zip3, area_providers in by_zip3.items():
        n = len(area_providers)
        if n == 0:
            continue

        # Collect area-level stats
        risk_scores  = [p.get("risk_score", 0) for p in area_providers]
        total_paids  = [p.get("total_paid", 0) or 0 for p in area_providers]
        area_billing = sum(total_paids)

        avg_risk = sum(risk_scores) / n

        flagged_count = sum(1 for s in risk_scores if s > settings.RISK_THRESHOLD)
        flagged_pct   = (flagged_count / n) * 100

        high_risk_count = sum(1 for s in risk_scores if s >= 50)

        # Billing concentration: top provider's share of total area billing
        max_paid = max(total_paids) if total_paids else 0
        billing_concentration = (max_paid / area_billing * 100) if area_billing > 0 else 0

        # Provider density anomaly: ratio vs global mean (capped at 5x)
        density_ratio = n / global_mean_count if global_mean_count > 0 else 1.0

        # ── Compute component scores (each normalised to 0-100) ──────────
        # avg_risk is already 0-100
        comp_avg_risk = min(avg_risk, 100.0)

        # flagged_pct is already 0-100
        comp_flagged_pct = min(flagged_pct, 100.0)

        # billing_concentration is already 0-100
        comp_billing_conc = min(billing_concentration, 100.0)

        # density_anomaly: scale ratio so 3x = 100
        comp_density = min((density_ratio / 3.0) * 100.0, 100.0)

        # high_risk_count: scale so 10 = 100
        comp_high_risk = min((high_risk_count / 10.0) * 100.0, 100.0)

        composite = (
            comp_avg_risk      * W_AVG_RISK
            + comp_flagged_pct * W_FLAGGED_PCT
            + comp_billing_conc * W_BILLING_CONC
            + comp_density     * W_DENSITY_ANOMALY
            + comp_high_risk   * W_HIGH_RISK_COUNT
        )
        composite = round(min(composite, 100.0), 1)

        # Collect unique states and cities for this area
        states: set[str] = set()
        cities: set[str] = set()
        for p in area_providers:
            st = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state", "")
            ci = p.get("city") or ""
            if st:
                states.add(st)
            if ci:
                cities.add(ci)

        hotspots.append({
            "zip3":                zip3,
            "composite_score":     composite,
            "severity":            _severity(composite),
            "provider_count":      n,
            "flagged_count":       flagged_count,
            "flagged_pct":         round(flagged_pct, 1),
            "high_risk_count":     high_risk_count,
            "avg_risk_score":      round(avg_risk, 1),
            "total_billing":       round(area_billing, 2),
            "billing_concentration": round(billing_concentration, 1),
            "density_ratio":       round(density_ratio, 2),
            "states":              sorted(states),
            "cities":              sorted(cities),
            "components": {
                "avg_risk":              round(comp_avg_risk, 1),
                "flagged_pct":           round(comp_flagged_pct, 1),
                "billing_concentration": round(comp_billing_conc, 1),
                "density_anomaly":       round(comp_density, 1),
                "high_risk_count":       round(comp_high_risk, 1),
            },
        })

    hotspots.sort(key=lambda h: h["composite_score"], reverse=True)
    return hotspots


def get_hotspot_detail(zip3: str) -> dict[str, Any] | None:
    """
    Return full detail for a single ZIP3 area, including top providers.
    """
    providers = get_prescanned()
    area_providers = [p for p in providers if _zip3(p) == zip3]
    if not area_providers:
        return None

    # Find this ZIP3 in the full hotspot list
    all_hotspots = compute_hotspots()
    hotspot = next((h for h in all_hotspots if h["zip3"] == zip3), None)
    if not hotspot:
        return None

    # Build top providers list (sorted by risk_score desc)
    area_providers.sort(key=lambda p: p.get("risk_score", 0), reverse=True)
    top_providers = []
    for p in area_providers[:20]:
        top_providers.append({
            "npi":           p.get("npi"),
            "provider_name": p.get("provider_name") or p.get("nppes", {}).get("name", "Unknown"),
            "risk_score":    p.get("risk_score", 0),
            "total_paid":    p.get("total_paid", 0),
            "total_claims":  p.get("total_claims", 0),
            "flag_count":    len(p.get("flags") or []),
            "state":         p.get("state", ""),
            "city":          p.get("city", ""),
        })

    return {
        **hotspot,
        "top_providers": top_providers,
    }
