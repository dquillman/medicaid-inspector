"""
DME (Durable Medical Equipment) Fraud Analyzer.

Detects DME-related fraud patterns using HCPCS E/K/L codes in Medicaid claims.

Signals:
  - High-cost DME concentration (wheelchairs, oxygen, prosthetics)
  - Unusual DME volume vs. peer average
  - DME without supporting E&M visit codes
  - Rental vs. purchase anomalies
"""
import logging
from data.duckdb_client import query_async, get_parquet_path

log = logging.getLogger(__name__)

# ── Reference data ───────────────────────────────────────────────────────────
# HCPCS E-codes: DME
# HCPCS K-codes: DME (CMS temporary codes)
# HCPCS L-codes: Orthotics / Prosthetics
DME_PREFIXES = ("E", "K", "L")

# High-cost DME items (common OIG audit targets)
HIGH_COST_DME = {
    "E1390",  # Oxygen concentrator
    "E0431",  # Portable gaseous oxygen system
    "E0260",  # Hospital bed semi-electric
    "E0601",  # CPAP device
    "E1161",  # Manual wheelchair
    "E1235",  # Power wheelchair
    "E1238",  # Power wheelchair heavy duty
    "E0470",  # RAD — respiratory assist device (BiPAP)
    "E0471",  # RAD with backup
    "K0823",  # Power wheelchair group 2
    "K0856",  # Power wheelchair group 3
    "K0861",  # Power wheelchair group 2, sling
    "K0869",  # Power add-on
    "L5301",  # Below knee prosthesis
    "L5321",  # Above knee prosthesis
    "L1843",  # Knee orthosis
    "L3000",  # Foot insert
}

# Codes that are typically rented (RR modifier), not purchased
TYPICALLY_RENTED = {
    "E1390",  # Oxygen concentrator
    "E0260",  # Hospital bed
    "E0601",  # CPAP
    "E0470",  # BiPAP
    "E0471",  # BiPAP with backup
    "E1161",  # Manual wheelchair (sometimes)
    "K0823",  # Power wheelchair
}

# E&M (Evaluation & Management) codes — needed to support DME orders
EM_PREFIXES = ("992", "993", "994", "995")  # 99201-99499 range


def _src() -> str:
    return f"read_parquet('{get_parquet_path()}')"


async def _check_columns() -> dict:
    """Check which columns exist."""
    sql = f"""
        SELECT column_name
        FROM (DESCRIBE SELECT * FROM {_src()} LIMIT 0)
    """
    rows = await query_async(sql)
    cols = {r["column_name"].upper() for r in rows}
    return {
        "has_hcpcs": "HCPCS_CODE" in cols,
        "columns": cols,
    }


async def analyze_provider(npi: str) -> dict:
    """Full DME analysis for a single provider."""
    col_info = await _check_columns()
    if not col_info["has_hcpcs"]:
        return {
            "npi": npi,
            "available": False,
            "note": "HCPCS_CODE column not found in dataset",
            "signals": [],
        }

    src = _src()

    # Get provider's DME codes
    dme_sql = f"""
        SELECT
            HCPCS_CODE AS code,
            SUM(TOTAL_PAID) AS total_paid,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND (UPPER(HCPCS_CODE) LIKE 'E%'
               OR UPPER(HCPCS_CODE) LIKE 'K%'
               OR UPPER(HCPCS_CODE) LIKE 'L%')
        GROUP BY HCPCS_CODE
        ORDER BY total_paid DESC
    """

    # Get provider totals
    total_sql = f"""
        SELECT
            SUM(TOTAL_PAID) AS total_paid,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
            COUNT(DISTINCT HCPCS_CODE) AS distinct_codes
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    """

    # Check for E&M codes (supporting documentation for DME)
    em_sql = f"""
        SELECT
            COUNT(DISTINCT HCPCS_CODE) AS em_code_count,
            SUM(TOTAL_CLAIMS) AS em_claims,
            SUM(TOTAL_PAID) AS em_paid
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND (HCPCS_CODE LIKE '992%'
               OR HCPCS_CODE LIKE '993%'
               OR HCPCS_CODE LIKE '994%'
               OR HCPCS_CODE LIKE '995%')
    """

    # Get peer stats for DME volume
    peer_sql = f"""
        WITH dme_providers AS (
            SELECT
                BILLING_PROVIDER_NPI_NUM AS npi,
                SUM(CASE WHEN UPPER(HCPCS_CODE) LIKE 'E%'
                         OR UPPER(HCPCS_CODE) LIKE 'K%'
                         OR UPPER(HCPCS_CODE) LIKE 'L%'
                    THEN TOTAL_PAID ELSE 0 END) AS dme_paid
            FROM {src}
            GROUP BY BILLING_PROVIDER_NPI_NUM
            HAVING dme_paid > 0
        )
        SELECT
            AVG(dme_paid) AS avg_dme_paid,
            MEDIAN(dme_paid) AS median_dme_paid,
            STDDEV(dme_paid) AS std_dme_paid,
            COUNT(*) AS peer_count
        FROM dme_providers
    """

    import asyncio
    dme_rows, total_rows, em_rows, peer_rows = await asyncio.gather(
        query_async(dme_sql),
        query_async(total_sql),
        query_async(em_sql),
        query_async(peer_sql),
    )

    total = total_rows[0] if total_rows else {}
    total_paid = total.get("total_paid", 0) or 0
    em = em_rows[0] if em_rows else {}
    peer = peer_rows[0] if peer_rows else {}

    signals = []
    dme_total_paid = sum(r.get("total_paid", 0) or 0 for r in dme_rows)
    dme_pct = (dme_total_paid / total_paid * 100) if total_paid > 0 else 0

    # Signal 1: High-cost DME concentration
    high_cost_paid = sum(
        r.get("total_paid", 0) or 0
        for r in dme_rows
        if r.get("code", "").upper() in HIGH_COST_DME
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
                "codes": [
                    r["code"] for r in dme_rows
                    if r.get("code", "").upper() in HIGH_COST_DME
                ],
            },
        })

    # Signal 2: Unusual DME volume vs peers
    avg_peer = peer.get("avg_dme_paid", 0) or 0
    std_peer = peer.get("std_dme_paid", 0) or 1
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
                    "peer_median": round(peer.get("median_dme_paid", 0) or 0, 2),
                    "z_score": round(z_score, 2),
                    "multiple": round(multiple, 1),
                    "peer_count": peer.get("peer_count", 0),
                },
            })

    # Signal 3: DME without supporting E&M codes
    em_claims = em.get("em_claims", 0) or 0
    dme_claims = sum(r.get("total_claims", 0) or 0 for r in dme_rows)
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

    # Signal 4: Rental vs. purchase — providers billing high-cost rental items
    rental_items_billed = [
        r for r in dme_rows
        if r.get("code", "").upper() in TYPICALLY_RENTED
    ]
    rental_paid = sum(r.get("total_paid", 0) or 0 for r in rental_items_billed)
    rental_pct = (rental_paid / total_paid * 100) if total_paid > 0 else 0
    if rental_pct > 30 and len(rental_items_billed) >= 2:
        signals.append({
            "signal": "rental_item_concentration",
            "score": min(rental_pct / 60, 1.0),
            "severity": "MEDIUM",
            "description": f"{rental_pct:.1f}% of billing from typically-rented DME items",
            "detail": {
                "rental_paid": round(rental_paid, 2),
                "pct": round(rental_pct, 1),
                "codes": [r["code"] for r in rental_items_billed],
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
                "code": r["code"],
                "total_paid": round(r.get("total_paid", 0) or 0, 2),
                "total_claims": r.get("total_claims", 0) or 0,
                "is_high_cost": r["code"].upper() in HIGH_COST_DME,
                "is_rental_type": r["code"].upper() in TYPICALLY_RENTED,
            }
            for r in dme_rows[:15]
        ],
        "peer_comparison": {
            "avg_dme_paid": round(avg_peer, 2),
            "median_dme_paid": round(peer.get("median_dme_paid", 0) or 0, 2),
            "peer_count": peer.get("peer_count", 0),
        },
        "signals": signals,
        "composite_risk": round(composite, 1),
    }


async def get_high_risk_providers(limit: int = 50) -> dict:
    """Find providers with the highest DME fraud risk indicators."""
    col_info = await _check_columns()
    if not col_info["has_hcpcs"]:
        return {
            "available": False,
            "note": "HCPCS_CODE column not found in dataset",
            "providers": [],
            "total": 0,
        }

    src = _src()

    sql = f"""
        WITH dme_providers AS (
            SELECT
                BILLING_PROVIDER_NPI_NUM AS npi,
                SUM(CASE WHEN UPPER(HCPCS_CODE) LIKE 'E%'
                         OR UPPER(HCPCS_CODE) LIKE 'K%'
                         OR UPPER(HCPCS_CODE) LIKE 'L%'
                    THEN TOTAL_PAID ELSE 0 END) AS dme_paid,
                SUM(TOTAL_PAID) AS total_paid,
                SUM(CASE WHEN UPPER(HCPCS_CODE) LIKE 'E%'
                         OR UPPER(HCPCS_CODE) LIKE 'K%'
                         OR UPPER(HCPCS_CODE) LIKE 'L%'
                    THEN TOTAL_CLAIMS ELSE 0 END) AS dme_claims,
                SUM(TOTAL_CLAIMS) AS total_claims,
                SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
                COUNT(DISTINCT CASE WHEN UPPER(HCPCS_CODE) LIKE 'E%'
                                     OR UPPER(HCPCS_CODE) LIKE 'K%'
                                     OR UPPER(HCPCS_CODE) LIKE 'L%'
                               THEN HCPCS_CODE END) AS dme_code_count,
                SUM(CASE WHEN UPPER(HCPCS_CODE) IN ({_in_list(HIGH_COST_DME)})
                    THEN TOTAL_PAID ELSE 0 END) AS high_cost_paid,
                SUM(CASE WHEN HCPCS_CODE LIKE '992%'
                         OR HCPCS_CODE LIKE '993%'
                         OR HCPCS_CODE LIKE '994%'
                         OR HCPCS_CODE LIKE '995%'
                    THEN TOTAL_CLAIMS ELSE 0 END) AS em_claims,
                SUM(CASE WHEN UPPER(HCPCS_CODE) IN ({_in_list(TYPICALLY_RENTED)})
                    THEN TOTAL_PAID ELSE 0 END) AS rental_paid
            FROM {src}
            GROUP BY BILLING_PROVIDER_NPI_NUM
            HAVING dme_paid > 0
        ),
        peer_stats AS (
            SELECT
                AVG(dme_paid) AS avg_dme,
                STDDEV(dme_paid) AS std_dme
            FROM dme_providers
        )
        SELECT dp.*,
            ROUND(dp.dme_paid / NULLIF(dp.total_paid, 0) * 100, 1) AS dme_pct,
            ROUND(dp.high_cost_paid / NULLIF(dp.total_paid, 0) * 100, 1) AS high_cost_pct,
            ROUND(dp.rental_paid / NULLIF(dp.total_paid, 0) * 100, 1) AS rental_pct,
            ROUND((dp.dme_paid - ps.avg_dme) / NULLIF(ps.std_dme, 0), 2) AS z_score
        FROM dme_providers dp
        CROSS JOIN peer_stats ps
        WHERE dp.dme_paid / NULLIF(dp.total_paid, 0) > 0.1
        ORDER BY dp.dme_paid DESC
        LIMIT {limit}
    """
    rows = await query_async(sql)

    from core.store import get_prescanned
    cache = get_prescanned()
    cache_map = {p["npi"]: p for p in cache} if cache else {}

    providers = []
    for r in rows:
        npi = r["npi"]
        cached = cache_map.get(npi, {})
        flags = []

        if (r.get("high_cost_pct") or 0) > 25:
            flags.append("High-cost DME concentration")
        if (r.get("z_score") or 0) > 2:
            flags.append("Unusual DME volume")
        dme_claims = r.get("dme_claims", 0) or 0
        em_claims = r.get("em_claims", 0) or 0
        if dme_claims > 10 and em_claims == 0:
            flags.append("DME without E&M visits")
        elif dme_claims > 10 and em_claims > 0 and dme_claims / em_claims > 5:
            flags.append("DME/E&M ratio imbalance")
        if (r.get("rental_pct") or 0) > 30:
            flags.append("Rental item concentration")

        risk = 0
        if flags:
            risk = min(len(flags) * 25 + (r.get("dme_pct", 0) or 0) * 0.5, 100)

        providers.append({
            "npi": npi,
            "provider_name": cached.get("provider_name", ""),
            "state": cached.get("state", ""),
            "total_paid": round(r.get("total_paid", 0) or 0, 2),
            "dme_paid": round(r.get("dme_paid", 0) or 0, 2),
            "dme_pct": r.get("dme_pct", 0) or 0,
            "dme_code_count": r.get("dme_code_count", 0) or 0,
            "high_cost_pct": r.get("high_cost_pct", 0) or 0,
            "dme_claims": dme_claims,
            "em_claims": em_claims,
            "rental_pct": r.get("rental_pct", 0) or 0,
            "z_score": r.get("z_score", 0) or 0,
            "total_benes": r.get("total_benes", 0) or 0,
            "flags": flags,
            "flag_count": len(flags),
            "dme_risk": round(risk, 1),
            "risk_score": cached.get("risk_score", 0),
        })

    providers.sort(key=lambda p: p["dme_risk"], reverse=True)

    return {
        "available": True,
        "providers": providers,
        "total": len(providers),
        "kpis": {
            "total_dme_providers": len(providers),
            "total_dme_billing": round(sum(p["dme_paid"] for p in providers), 2),
            "avg_dme_pct": round(
                sum(p["dme_pct"] for p in providers) / max(len(providers), 1), 1
            ),
            "flagged_count": sum(1 for p in providers if p["flag_count"] > 0),
            "high_cost_count": sum(
                1 for p in providers if p["high_cost_pct"] > 25
            ),
            "no_em_count": sum(
                1 for p in providers if p["dme_claims"] > 10 and p["em_claims"] == 0
            ),
        },
    }


def _in_list(codes: set) -> str:
    """Format a set of codes for SQL IN clause."""
    return ", ".join(f"'{c}'" for c in sorted(codes))
