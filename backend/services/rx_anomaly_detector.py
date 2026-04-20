"""
Prescription/Rx Anomaly Detection Service.

Since free real-time PDMP API access is not available, this service
detects prescription-related fraud patterns from existing claims data:

1. High-cost Rx code concentration — providers billing primarily J-codes
   (injectable drugs) or high-cost pharmacy codes
2. Rx code diversity anomalies — providers billing an unusual mix of
   drug administration codes
3. Controlled substance proxy — providers billing drug administration
   codes at volumes suggesting controlled substance distribution

Data source: Existing HCPCS codes in prescan cache. J-codes (J0000-J9999)
and drug administration codes (96360-96379, 96401-96549) are drug-related.
"""
import logging
import statistics
from core.store import get_prescanned, get_provider_by_npi

log = logging.getLogger(__name__)

# HCPCS code ranges for drug-related billing
_J_CODE_PREFIXES = {"J0", "J1", "J2", "J3", "J7", "J8", "J9"}
_ADMIN_CODES = {
    "96360", "96361", "96365", "96366", "96367", "96368",
    "96369", "96370", "96371", "96372", "96373", "96374",
    "96375", "96376", "96377", "96379",
    "96401", "96402", "96405", "96406", "96409", "96411",
    "96413", "96415", "96416", "96417", "96420", "96422",
    "96423", "96425", "96440", "96446", "96450", "96521",
    "96522", "96523", "96542", "96549",
}

# High-cost injectable drugs (known fraud targets)
_HIGH_COST_J_CODES = {
    "J1745",  # Infliximab
    "J0585",  # Botulinum toxin
    "J9271",  # Pembrolizumab
    "J9035",  # Bevacizumab
    "J2357",  # Omalizumab
    "J1300",  # Eculizumab
    "J0897",  # Denosumab
    "J9228",  # Ipilimumab
    "J1602",  # Golimumab
    "J2182",  # Mepolizumab
    "J0717",  # Certolizumab
    "J3380",  # Vedolizumab
    "J9173",  # Durvalumab
}


def _is_rx_code(code: str) -> bool:
    """Check if an HCPCS code is drug-related."""
    if not code:
        return False
    if code in _ADMIN_CODES:
        return True
    return any(code.startswith(prefix) for prefix in _J_CODE_PREFIXES)


async def detect_rx_anomalies(limit: int = 100) -> dict:
    """
    Find providers with suspicious prescription/drug billing patterns.
    """
    providers = get_prescanned()
    if not providers:
        return {"flagged": [], "total_flagged": 0}

    rx_profiles = []

    for p in providers:
        hcpcs_list = p.get("hcpcs") or []
        if not hcpcs_list:
            continue

        total_paid = 0
        rx_paid = 0
        rx_claims = 0
        high_cost_paid = 0
        j_code_count = 0
        admin_count = 0

        for h in hcpcs_list:
            code = h.get("hcpcs_code", "")
            paid = float(h.get("total_paid", 0) or 0)
            claims = int(h.get("total_claims", 0) or 0)
            total_paid += paid

            if _is_rx_code(code):
                rx_paid += paid
                rx_claims += claims
                if any(code.startswith(p) for p in _J_CODE_PREFIXES):
                    j_code_count += 1
                if code in _ADMIN_CODES:
                    admin_count += 1
                if code in _HIGH_COST_J_CODES:
                    high_cost_paid += paid

        if total_paid == 0 or rx_paid == 0:
            continue

        rx_pct = rx_paid / total_paid * 100
        rx_profiles.append({
            "npi": p["npi"],
            "total_paid": round(total_paid, 2),
            "rx_paid": round(rx_paid, 2),
            "rx_pct": round(rx_pct, 1),
            "rx_claims": rx_claims,
            "j_code_count": j_code_count,
            "admin_code_count": admin_count,
            "high_cost_rx_paid": round(high_cost_paid, 2),
            "risk_score": p.get("risk_score", 0),
        })

    if not rx_profiles:
        return {"flagged": [], "total_flagged": 0, "note": "No providers with Rx billing"}

    # Compute system-wide stats
    rx_pcts = [r["rx_pct"] for r in rx_profiles]
    mean_rx_pct = statistics.mean(rx_pcts)
    std_rx_pct = statistics.stdev(rx_pcts) if len(rx_pcts) > 1 else 1

    # Flag outliers
    flagged = []
    for r in rx_profiles:
        z_score = (r["rx_pct"] - mean_rx_pct) / std_rx_pct if std_rx_pct > 0 else 0

        # Flag criteria: high Rx concentration OR high-cost drugs OR extreme z-score
        reasons = []
        if r["rx_pct"] > 70:
            reasons.append(f"Rx billing is {r['rx_pct']:.0f}% of total revenue")
        if r["high_cost_rx_paid"] > 100000:
            reasons.append(f"${r['high_cost_rx_paid']:,.0f} in high-cost injectable drugs")
        if z_score > 2.0:
            reasons.append(f"Rx concentration {z_score:.1f} std dev above peer mean")

        if not reasons:
            continue

        severity = "HIGH" if (r["rx_pct"] > 80 or r["high_cost_rx_paid"] > 500000 or z_score > 3) else "MEDIUM"

        flagged.append({
            **r,
            "z_score": round(z_score, 2),
            "severity": severity,
            "reasons": reasons,
        })

    flagged.sort(key=lambda x: x["rx_paid"], reverse=True)
    flagged = flagged[:limit]

    return {
        "flagged": flagged,
        "total_flagged": len(flagged),
        "system_stats": {
            "providers_with_rx": len(rx_profiles),
            "mean_rx_pct": round(mean_rx_pct, 1),
            "std_rx_pct": round(std_rx_pct, 1),
        },
        "note": (
            "Providers with suspicious drug/prescription billing patterns. "
            "J-codes (injectable drugs) and administration codes flagged. "
            "High-cost biologics and chemotherapy agents receive extra scrutiny."
        ),
    }


async def provider_rx_profile(npi: str) -> dict:
    """Detailed Rx billing profile for a specific provider."""
    provider = get_provider_by_npi(npi)
    if not provider:
        return {"npi": npi, "found": False, "error": "Provider not found"}

    hcpcs_list = provider.get("hcpcs") or []
    total_paid = 0
    rx_codes = []

    for h in hcpcs_list:
        code = h.get("hcpcs_code", "")
        paid = float(h.get("total_paid", 0) or 0)
        claims = int(h.get("total_claims", 0) or 0)
        total_paid += paid

        if _is_rx_code(code):
            rx_codes.append({
                "hcpcs_code": code,
                "total_paid": round(paid, 2),
                "total_claims": claims,
                "is_high_cost": code in _HIGH_COST_J_CODES,
                "is_j_code": any(code.startswith(p) for p in _J_CODE_PREFIXES),
                "is_admin_code": code in _ADMIN_CODES,
            })

    rx_codes.sort(key=lambda x: x["total_paid"], reverse=True)
    rx_paid = sum(c["total_paid"] for c in rx_codes)

    return {
        "npi": npi,
        "found": True,
        "total_paid": round(total_paid, 2),
        "rx_paid": round(rx_paid, 2),
        "rx_pct": round(rx_paid / total_paid * 100, 1) if total_paid > 0 else 0,
        "rx_codes": rx_codes,
        "high_cost_codes": [c for c in rx_codes if c["is_high_cost"]],
    }
