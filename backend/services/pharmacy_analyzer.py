"""
Pharmacy / Drug Fraud Analyzer.

Detects pharmacy and drug-related fraud patterns using HCPCS J-codes
(drug injection codes), NDC codes (if available), and controlled substance
indicators in Medicaid claims data.

Signals:
  - High-cost drug concentration
  - Controlled substance over-prescribing
  - Dispensing pattern anomalies (early refills, unusual quantities)
  - Drug diversion indicators (high controlled volume + geographic dispersion)
"""
import logging
from data.duckdb_client import query_async, get_parquet_path

log = logging.getLogger(__name__)

# ── Reference data ───────────────────────────────────────────────────────────
# HCPCS J-codes: injectable drugs administered by providers
# High-cost brand-name drugs (common OIG targets)
HIGH_COST_J_CODES = {
    "J0585",  # Botulinum toxin (Botox)
    "J1745",  # Infliximab (Remicade)
    "J2315",  # Naltrexone (Vivitrol)
    "J9035",  # Bevacizumab (Avastin)
    "J9310",  # Rituximab
    "J1300",  # Eculizumab (Soliris)
    "J0178",  # Aflibercept (Eylea)
    "J2350",  # Ocrelizumab (Ocrevus)
    "J9299",  # Nivolumab (Opdivo)
    "J9271",  # Pembrolizumab (Keytruda)
    "J0129",  # Abatacept (Orencia)
    "J3490",  # Unclassified drugs (often used for fraud)
    "J3590",  # Unclassified biologics
}

# Controlled substance HCPCS (Schedule II-IV)
CONTROLLED_SUBSTANCE_CODES = {
    "J2175",  # Meperidine (Schedule II)
    "J2270",  # Morphine (Schedule II)
    "J2310",  # Naloxone combos
    "J3010",  # Fentanyl (Schedule II)
    "J2315",  # Naltrexone (used in opioid treatment)
    "J0592",  # Buprenorphine (Schedule III)
    "J0575",  # Buprenorphine/naloxone
    "J2060",  # Lorazepam (Schedule IV)
    "J2250",  # Midazolam (Schedule IV)
    "J1170",  # Hydromorphone (Schedule II)
}

# All J-codes are drug injection codes
J_CODE_PREFIX = "J"


def _src() -> str:
    return f"read_parquet('{get_parquet_path()}')"


async def _check_columns() -> dict:
    """Check which drug-related columns exist in the dataset."""
    sql = f"""
        SELECT column_name
        FROM (DESCRIBE SELECT * FROM {_src()} LIMIT 0)
    """
    rows = await query_async(sql)
    cols = {r["column_name"].upper() for r in rows}
    return {
        "has_hcpcs": "HCPCS_CODE" in cols,
        "has_ndc": "NDC" in cols or "NDC_CODE" in cols,
        "has_state": "BILLING_PROVIDER_STATE" in cols or any("STATE" in c for c in cols),
        "columns": cols,
    }


async def analyze_provider(npi: str) -> dict:
    """Full pharmacy analysis for a single provider."""
    col_info = await _check_columns()
    if not col_info["has_hcpcs"]:
        return {
            "npi": npi,
            "available": False,
            "note": "HCPCS_CODE column not found in dataset",
            "signals": [],
        }

    src = _src()

    # Get provider's drug codes (J-codes)
    drug_sql = f"""
        SELECT
            HCPCS_CODE AS code,
            SUM(TOTAL_PAID) AS total_paid,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND UPPER(HCPCS_CODE) LIKE 'J%'
        GROUP BY HCPCS_CODE
        ORDER BY total_paid DESC
    """

    # Get provider's total billing for comparison
    total_sql = f"""
        SELECT
            SUM(TOTAL_PAID) AS total_paid,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
            COUNT(DISTINCT HCPCS_CODE) AS distinct_codes
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    """

    # Get monthly drug billing for pattern analysis
    monthly_sql = f"""
        SELECT
            HCPCS_CODE AS code,
            CLAIM_FROM_MONTH AS month,
            SUM(TOTAL_PAID) AS paid,
            SUM(TOTAL_CLAIMS) AS claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS benes
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND UPPER(HCPCS_CODE) LIKE 'J%'
        GROUP BY HCPCS_CODE, CLAIM_FROM_MONTH
        ORDER BY HCPCS_CODE, CLAIM_FROM_MONTH
    """

    drug_rows, total_rows, monthly_rows = await _parallel_queries(
        drug_sql, total_sql, monthly_sql
    )

    total = total_rows[0] if total_rows else {}
    total_paid = total.get("total_paid", 0) or 0

    signals = []
    drug_total_paid = sum(r.get("total_paid", 0) or 0 for r in drug_rows)
    drug_pct = (drug_total_paid / total_paid * 100) if total_paid > 0 else 0

    # Signal 1: High-cost drug concentration
    high_cost_paid = sum(
        r.get("total_paid", 0) or 0
        for r in drug_rows
        if r.get("code", "").upper() in HIGH_COST_J_CODES
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
                "codes": [
                    r["code"] for r in drug_rows
                    if r.get("code", "").upper() in HIGH_COST_J_CODES
                ],
            },
        })

    # Signal 2: Controlled substance volume
    controlled_paid = sum(
        r.get("total_paid", 0) or 0
        for r in drug_rows
        if r.get("code", "").upper() in CONTROLLED_SUBSTANCE_CODES
    )
    controlled_claims = sum(
        r.get("total_claims", 0) or 0
        for r in drug_rows
        if r.get("code", "").upper() in CONTROLLED_SUBSTANCE_CODES
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

    # Signal 3: Early refill patterns (same drug code billed in consecutive months)
    early_refills = _detect_early_refills(monthly_rows)
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

    # Signal 4: J3490/J3590 concentration (unclassified drug codes — common fraud vector)
    unclassified_paid = sum(
        r.get("total_paid", 0) or 0
        for r in drug_rows
        if r.get("code", "").upper() in ("J3490", "J3590")
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

    # Compute composite risk
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
                "code": r["code"],
                "total_paid": round(r.get("total_paid", 0) or 0, 2),
                "total_claims": r.get("total_claims", 0) or 0,
                "is_high_cost": r["code"].upper() in HIGH_COST_J_CODES,
                "is_controlled": r["code"].upper() in CONTROLLED_SUBSTANCE_CODES,
            }
            for r in drug_rows[:15]
        ],
        "signals": signals,
        "composite_risk": round(composite, 1),
    }


async def get_high_risk_providers(limit: int = 50) -> dict:
    """Find providers with the highest pharmacy fraud risk indicators."""
    col_info = await _check_columns()
    if not col_info["has_hcpcs"]:
        return {
            "available": False,
            "note": "HCPCS_CODE column not found in dataset",
            "providers": [],
            "total": 0,
        }

    src = _src()

    # Providers with significant J-code billing
    sql = f"""
        WITH drug_providers AS (
            SELECT
                BILLING_PROVIDER_NPI_NUM AS npi,
                SUM(CASE WHEN UPPER(HCPCS_CODE) LIKE 'J%' THEN TOTAL_PAID ELSE 0 END) AS drug_paid,
                SUM(TOTAL_PAID) AS total_paid,
                SUM(CASE WHEN UPPER(HCPCS_CODE) LIKE 'J%' THEN TOTAL_CLAIMS ELSE 0 END) AS drug_claims,
                SUM(TOTAL_CLAIMS) AS total_claims,
                SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
                COUNT(DISTINCT CASE WHEN UPPER(HCPCS_CODE) LIKE 'J%' THEN HCPCS_CODE END) AS drug_code_count,
                SUM(CASE WHEN UPPER(HCPCS_CODE) IN ({_in_list(HIGH_COST_J_CODES)}) THEN TOTAL_PAID ELSE 0 END) AS high_cost_paid,
                SUM(CASE WHEN UPPER(HCPCS_CODE) IN ({_in_list(CONTROLLED_SUBSTANCE_CODES)}) THEN TOTAL_PAID ELSE 0 END) AS controlled_paid,
                SUM(CASE WHEN UPPER(HCPCS_CODE) IN ('J3490','J3590') THEN TOTAL_PAID ELSE 0 END) AS unclassified_paid
            FROM {src}
            GROUP BY BILLING_PROVIDER_NPI_NUM
            HAVING drug_paid > 0
        )
        SELECT *,
            ROUND(drug_paid / NULLIF(total_paid, 0) * 100, 1) AS drug_pct,
            ROUND(high_cost_paid / NULLIF(total_paid, 0) * 100, 1) AS high_cost_pct,
            ROUND(controlled_paid / NULLIF(total_paid, 0) * 100, 1) AS controlled_pct,
            ROUND(unclassified_paid / NULLIF(total_paid, 0) * 100, 1) AS unclassified_pct
        FROM drug_providers
        WHERE drug_paid / NULLIF(total_paid, 0) > 0.1
        ORDER BY drug_paid DESC
        LIMIT {limit}
    """
    rows = await query_async(sql)

    # Enrich with names from prescan cache
    from core.store import get_prescanned
    cache = get_prescanned()
    cache_map = {p["npi"]: p for p in cache} if cache else {}

    providers = []
    for r in rows:
        npi = r["npi"]
        cached = cache_map.get(npi, {})
        flags = []
        if (r.get("high_cost_pct") or 0) > 30:
            flags.append("High-cost drug concentration")
        if (r.get("controlled_pct") or 0) > 15:
            flags.append("Controlled substance volume")
        if (r.get("unclassified_pct") or 0) > 10:
            flags.append("Unclassified drug codes")

        risk = 0
        if flags:
            risk = min(len(flags) * 30 + (r.get("drug_pct", 0) or 0) * 0.5, 100)

        providers.append({
            "npi": npi,
            "provider_name": cached.get("provider_name", ""),
            "state": cached.get("state", ""),
            "total_paid": round(r.get("total_paid", 0) or 0, 2),
            "drug_paid": round(r.get("drug_paid", 0) or 0, 2),
            "drug_pct": r.get("drug_pct", 0) or 0,
            "drug_code_count": r.get("drug_code_count", 0) or 0,
            "high_cost_pct": r.get("high_cost_pct", 0) or 0,
            "controlled_pct": r.get("controlled_pct", 0) or 0,
            "unclassified_pct": r.get("unclassified_pct", 0) or 0,
            "total_claims": r.get("total_claims", 0) or 0,
            "total_benes": r.get("total_benes", 0) or 0,
            "flags": flags,
            "flag_count": len(flags),
            "pharmacy_risk": round(risk, 1),
            "risk_score": cached.get("risk_score", 0),
        })

    # Sort by pharmacy risk descending
    providers.sort(key=lambda p: p["pharmacy_risk"], reverse=True)

    return {
        "available": True,
        "providers": providers,
        "total": len(providers),
        "kpis": {
            "total_drug_providers": len(providers),
            "total_drug_billing": round(sum(p["drug_paid"] for p in providers), 2),
            "avg_drug_pct": round(
                sum(p["drug_pct"] for p in providers) / max(len(providers), 1), 1
            ),
            "flagged_count": sum(1 for p in providers if p["flag_count"] > 0),
            "high_cost_count": sum(
                1 for p in providers if p["high_cost_pct"] > 30
            ),
            "controlled_count": sum(
                1 for p in providers if p["controlled_pct"] > 15
            ),
        },
    }


def _detect_early_refills(monthly_rows: list[dict]) -> list[dict]:
    """Detect same drug code billed in consecutive months (potential early refills)."""
    from collections import defaultdict

    by_code = defaultdict(list)
    for r in monthly_rows:
        code = r.get("code", "")
        month = r.get("month", "")
        if code and month:
            by_code[code].append(r)

    refills = []
    for code, months in by_code.items():
        sorted_months = sorted(months, key=lambda x: x.get("month", ""))
        for i in range(1, len(sorted_months)):
            prev = sorted_months[i - 1]
            curr = sorted_months[i]
            prev_m = prev.get("month", "")
            curr_m = curr.get("month", "")
            # Check if months are within 15 days (same or consecutive month)
            if prev_m and curr_m and _months_apart(prev_m, curr_m) <= 1:
                prev_claims = prev.get("claims", 0) or 0
                curr_claims = curr.get("claims", 0) or 0
                if prev_claims > 0 and curr_claims > 0:
                    refills.append({
                        "code": code,
                        "month1": prev_m,
                        "month2": curr_m,
                        "claims1": prev_claims,
                        "claims2": curr_claims,
                    })
    return refills


def _months_apart(m1: str, m2: str) -> int:
    """Compute months between two YYYY-MM date strings."""
    try:
        y1, mo1 = int(m1[:4]), int(m1[5:7])
        y2, mo2 = int(m2[:4]), int(m2[5:7])
        return abs((y2 * 12 + mo2) - (y1 * 12 + mo1))
    except (ValueError, IndexError):
        return 999


def _in_list(codes: set) -> str:
    """Format a set of codes for SQL IN clause."""
    return ", ".join(f"'{c}'" for c in sorted(codes))


async def _parallel_queries(*sqls: str) -> list[list[dict]]:
    """Run multiple queries concurrently."""
    import asyncio
    results = await asyncio.gather(*(query_async(sql) for sql in sqls))
    return list(results)
