"""
Claim-level fraud pattern detection.

Detects five categories of claim-level fraud:
  1. Unbundling — billing component codes separately instead of bundled code
  2. Duplicate claims — identical/near-identical claims
  3. Place-of-service violations — procedure/setting mismatches
  4. Modifier abuse — unusual modifier usage rates
  5. Impossible day patterns — physically impossible billing volumes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from data.duckdb_client import query_async, get_parquet_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Unbundling — common bundle groups
# ---------------------------------------------------------------------------

BUNDLE_GROUPS: list[dict[str, Any]] = [
    {
        "name": "CBC Panel",
        "bundled_code": "85025",
        "component_codes": ["85004", "85007", "85009", "85014", "85018", "85041", "85048"],
        "description": "Complete Blood Count — should be billed as 85025, not individual component codes",
    },
    {
        "name": "Comprehensive Metabolic Panel",
        "bundled_code": "80053",
        "component_codes": ["82040", "82310", "82374", "82435", "82565", "82947", "84075", "84132", "84155", "84295", "84450", "84460", "82247", "82248"],
        "description": "CMP should be billed as 80053, not individual analytes",
    },
    {
        "name": "Basic Metabolic Panel",
        "bundled_code": "80048",
        "component_codes": ["82310", "82374", "82435", "82565", "82947", "84132", "84295", "82040"],
        "description": "BMP should be billed as 80048, not individual analytes",
    },
    {
        "name": "Lipid Panel",
        "bundled_code": "80061",
        "component_codes": ["82465", "83718", "83721", "84478"],
        "description": "Lipid Panel should be billed as 80061",
    },
    {
        "name": "Hepatic Function Panel",
        "bundled_code": "80076",
        "component_codes": ["82040", "82247", "82248", "84075", "84155", "84450", "84460"],
        "description": "Liver function tests should be billed as 80076",
    },
    {
        "name": "Renal Function Panel",
        "bundled_code": "80069",
        "component_codes": ["82040", "82310", "82374", "82435", "82565", "82947", "84132", "84295", "84520"],
        "description": "Renal function tests should be billed as 80069",
    },
    {
        "name": "Thyroid Panel",
        "bundled_code": "80091",
        "component_codes": ["84436", "84439", "84443"],
        "description": "Thyroid panel should be billed as 80091",
    },
]


# ---------------------------------------------------------------------------
# 2. Place-of-service validation rules
# ---------------------------------------------------------------------------

# Surgical procedure code ranges that should NOT appear in office/home settings
SURGICAL_CODE_RANGES = [
    ("10021", "10022"),  # Fine needle aspiration
    ("19000", "19499"),  # Breast surgery
    ("20000", "29999"),  # Musculoskeletal surgery
    ("30000", "32999"),  # Respiratory surgery
    ("33010", "37799"),  # Cardiovascular surgery
    ("38100", "38999"),  # Hemic/Lymphatic surgery
    ("40490", "49999"),  # Digestive surgery
    ("50010", "53899"),  # Urinary surgery
    ("54000", "55899"),  # Male genital surgery
    ("56405", "58999"),  # Female genital surgery
    ("60000", "60699"),  # Endocrine surgery
]

# Inpatient-only procedure indicators
INPATIENT_ONLY_PREFIXES = ["99221", "99222", "99223", "99231", "99232", "99233", "99238", "99239"]

# Place of service codes
POS_OFFICE = ["11"]
POS_HOME = ["12"]
POS_INPATIENT = ["21"]
POS_OUTPATIENT = ["22", "24"]

# E&M code ranges
EM_CODE_PREFIXES = ["9920", "9921", "9923", "9924", "9925", "9928", "9930"]


# ---------------------------------------------------------------------------
# Modifier definitions
# ---------------------------------------------------------------------------

MODIFIER_THRESHOLDS = {
    "25": {
        "name": "Significant, Separately Identifiable E&M",
        "threshold_pct": 40.0,
        "description": "Modifier -25 used on >40% of E&M claims suggests routine upcoding",
    },
    "59": {
        "name": "Distinct Procedural Service",
        "threshold_pct": 30.0,
        "description": "Modifier -59 overuse suggests unbundling or bypassing NCCI edits",
    },
    "76": {
        "name": "Repeat Procedure, Same Physician",
        "threshold_pct": 20.0,
        "description": "Modifier -76 overuse suggests duplicate billing disguised as repeats",
    },
    "77": {
        "name": "Repeat Procedure, Different Physician",
        "threshold_pct": 15.0,
        "description": "Modifier -77 overuse suggests questionable repeat procedures",
    },
}


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

async def detect_unbundling(limit: int = 100) -> list[dict]:
    """
    Identify providers billing component codes separately when a bundled
    code should be used. Looks for providers who bill 3+ component codes
    from a bundle group without billing the bundled code.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    results: list[dict] = []

    for bundle in BUNDLE_GROUPS:
        components = bundle["component_codes"]
        bundled = bundle["bundled_code"]
        comp_list = ", ".join(f"'{c}'" for c in components)

        sql = f"""
        WITH component_billing AS (
            SELECT
                BILLING_PROVIDER_NPI_NUM AS npi,
                COUNT(DISTINCT HCPCS_CODE) AS component_count,
                SUM(TOTAL_CLAIMS) AS component_claims,
                SUM(TOTAL_PAID) AS component_paid,
                LIST(DISTINCT HCPCS_CODE) AS codes_billed
            FROM {src}
            WHERE HCPCS_CODE IN ({comp_list})
            GROUP BY BILLING_PROVIDER_NPI_NUM
            HAVING COUNT(DISTINCT HCPCS_CODE) >= 3
        ),
        bundled_billing AS (
            SELECT
                BILLING_PROVIDER_NPI_NUM AS npi,
                SUM(TOTAL_CLAIMS) AS bundled_claims
            FROM {src}
            WHERE HCPCS_CODE = '{bundled}'
            GROUP BY BILLING_PROVIDER_NPI_NUM
        )
        SELECT
            cb.npi,
            cb.component_count,
            cb.component_claims,
            cb.component_paid,
            cb.codes_billed,
            COALESCE(bb.bundled_claims, 0) AS bundled_claims,
            CASE WHEN COALESCE(bb.bundled_claims, 0) = 0
                 THEN 1.0
                 ELSE cb.component_claims::DOUBLE / (cb.component_claims + bb.bundled_claims)
            END AS unbundling_rate
        FROM component_billing cb
        LEFT JOIN bundled_billing bb ON cb.npi = bb.npi
        WHERE COALESCE(bb.bundled_claims, 0) = 0
           OR cb.component_claims::DOUBLE / (cb.component_claims + COALESCE(bb.bundled_claims, 0)) > 0.5
        ORDER BY cb.component_paid DESC
        LIMIT {limit}
        """
        try:
            rows = await query_async(sql)
            for r in rows:
                codes_billed = r.get("codes_billed", [])
                if isinstance(codes_billed, str):
                    codes_billed = [codes_billed]
                results.append({
                    "npi": str(r["npi"]),
                    "bundle_name": bundle["name"],
                    "bundled_code": bundled,
                    "component_count": r["component_count"],
                    "component_claims": r["component_claims"],
                    "component_paid": float(r["component_paid"]),
                    "bundled_claims": r["bundled_claims"],
                    "unbundling_rate": round(float(r["unbundling_rate"]), 3),
                    "codes_billed": codes_billed,
                    "description": bundle["description"],
                    "severity": "CRITICAL" if r["unbundling_rate"] >= 0.9 else ("HIGH" if r["unbundling_rate"] >= 0.7 else "MEDIUM"),
                })
        except Exception as e:
            logger.warning("Unbundling detection error for %s: %s", bundle["name"], e)

    results.sort(key=lambda x: x["component_paid"], reverse=True)
    return results[:limit]


async def detect_duplicates(limit: int = 100) -> list[dict]:
    """
    Find providers with high rates of duplicate claim patterns —
    same NPI + same HCPCS + same month with identical paid amounts.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    sql = f"""
    WITH dup_clusters AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            HCPCS_CODE AS hcpcs_code,
            CLAIM_FROM_MONTH AS month,
            TOTAL_PAID AS paid_amount,
            COUNT(*) AS occurrence_count,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_PAID) AS total_paid
        FROM {src}
        GROUP BY
            BILLING_PROVIDER_NPI_NUM,
            HCPCS_CODE,
            CLAIM_FROM_MONTH,
            TOTAL_PAID
        HAVING COUNT(*) >= 2
    ),
    provider_summary AS (
        SELECT
            npi,
            COUNT(*) AS duplicate_clusters,
            SUM(occurrence_count) AS total_duplicate_lines,
            SUM(total_paid) AS duplicate_paid,
            MAX(occurrence_count) AS max_occurrences,
            LIST(DISTINCT hcpcs_code) AS affected_codes
        FROM dup_clusters
        GROUP BY npi
    ),
    provider_total AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_PAID) AS all_paid
        FROM {src}
        GROUP BY BILLING_PROVIDER_NPI_NUM
    )
    SELECT
        ps.npi,
        ps.duplicate_clusters,
        ps.total_duplicate_lines,
        ps.duplicate_paid,
        ps.max_occurrences,
        ps.affected_codes,
        pt.all_paid,
        ps.duplicate_paid / NULLIF(pt.all_paid, 0) AS duplicate_rate
    FROM provider_summary ps
    JOIN provider_total pt ON ps.npi = pt.npi
    WHERE ps.duplicate_clusters >= 2
    ORDER BY ps.duplicate_paid DESC
    LIMIT {limit}
    """
    try:
        rows = await query_async(sql)
        results = []
        for r in rows:
            affected = r.get("affected_codes", [])
            if isinstance(affected, str):
                affected = [affected]
            dup_rate = float(r.get("duplicate_rate", 0) or 0)
            results.append({
                "npi": str(r["npi"]),
                "duplicate_clusters": r["duplicate_clusters"],
                "total_duplicate_lines": r["total_duplicate_lines"],
                "duplicate_paid": float(r["duplicate_paid"]),
                "max_occurrences": r["max_occurrences"],
                "affected_codes": affected[:10],
                "all_paid": float(r["all_paid"]),
                "duplicate_rate": round(dup_rate, 3),
                "severity": "CRITICAL" if dup_rate >= 0.5 else ("HIGH" if dup_rate >= 0.25 else "MEDIUM"),
            })
        return results
    except Exception as e:
        logger.warning("Duplicate detection error: %s", e)
        return []


async def detect_pos_violations(limit: int = 100) -> list[dict]:
    """
    Cross-reference billed HCPCS codes against place-of-service norms.
    Flags surgical codes billed from office/home settings by looking at
    code patterns that suggest facility-level procedures done in non-facility settings.
    """
    src = f"read_parquet('{get_parquet_path()}')"

    # Build surgical code filter
    surgical_conditions = []
    for start, end in SURGICAL_CODE_RANGES:
        surgical_conditions.append(
            f"(CAST(HCPCS_CODE AS INTEGER) BETWEEN {start} AND {end})"
        )
    surgical_where = " OR ".join(surgical_conditions)

    # Detect providers billing high rates of surgical codes
    # (which should typically be in facility settings)
    # combined with codes suggesting non-facility billing
    sql = f"""
    WITH surgical_billing AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            COUNT(DISTINCT HCPCS_CODE) AS surgical_code_count,
            SUM(TOTAL_CLAIMS) AS surgical_claims,
            SUM(TOTAL_PAID) AS surgical_paid,
            LIST(DISTINCT HCPCS_CODE ORDER BY TOTAL_PAID DESC) AS surgical_codes
        FROM {src}
        WHERE TRY_CAST(HCPCS_CODE AS INTEGER) IS NOT NULL
          AND ({surgical_where})
        GROUP BY BILLING_PROVIDER_NPI_NUM
    ),
    office_em AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_CLAIMS) AS office_em_claims,
            SUM(TOTAL_PAID) AS office_em_paid
        FROM {src}
        WHERE HCPCS_CODE LIKE '9921%'
           OR HCPCS_CODE LIKE '9920%'
        GROUP BY BILLING_PROVIDER_NPI_NUM
    ),
    provider_total AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_PAID) AS total_paid,
            COUNT(DISTINCT HCPCS_CODE) AS total_codes
        FROM {src}
        GROUP BY BILLING_PROVIDER_NPI_NUM
    )
    SELECT
        sb.npi,
        sb.surgical_code_count,
        sb.surgical_claims,
        sb.surgical_paid,
        sb.surgical_codes,
        COALESCE(oe.office_em_claims, 0) AS office_em_claims,
        pt.total_claims,
        pt.total_paid,
        pt.total_codes,
        sb.surgical_claims::DOUBLE / NULLIF(pt.total_claims, 0) AS surgical_ratio,
        COALESCE(oe.office_em_claims, 0)::DOUBLE / NULLIF(pt.total_claims, 0) AS office_ratio
    FROM surgical_billing sb
    JOIN provider_total pt ON sb.npi = pt.npi
    LEFT JOIN office_em oe ON sb.npi = oe.npi
    WHERE sb.surgical_claims >= 5
      AND COALESCE(oe.office_em_claims, 0) > 0
      AND sb.surgical_claims::DOUBLE / NULLIF(pt.total_claims, 0) > 0.2
    ORDER BY sb.surgical_paid DESC
    LIMIT {limit}
    """
    try:
        rows = await query_async(sql)
        results = []
        for r in rows:
            codes = r.get("surgical_codes", [])
            if isinstance(codes, str):
                codes = [codes]
            surg_ratio = float(r.get("surgical_ratio", 0) or 0)
            results.append({
                "npi": str(r["npi"]),
                "surgical_code_count": r["surgical_code_count"],
                "surgical_claims": r["surgical_claims"],
                "surgical_paid": float(r["surgical_paid"]),
                "surgical_codes": codes[:10],
                "office_em_claims": r["office_em_claims"],
                "total_claims": r["total_claims"],
                "total_paid": float(r["total_paid"]),
                "surgical_ratio": round(surg_ratio, 3),
                "office_ratio": round(float(r.get("office_ratio", 0) or 0), 3),
                "violation_type": "surgical_in_office",
                "severity": "CRITICAL" if surg_ratio >= 0.5 else ("HIGH" if surg_ratio >= 0.3 else "MEDIUM"),
            })
        return results
    except Exception as e:
        logger.warning("POS violation detection error: %s", e)
        return []


async def detect_modifier_abuse(limit: int = 100) -> list[dict]:
    """
    Track modifier usage patterns per provider. Since the Parquet data
    may not have modifier columns, we approximate by looking for HCPCS
    codes that commonly carry modifiers and detect unusual patterns.

    We look for providers with unusually high billing of modifier-associated
    code patterns (e.g., high E&M with procedure combos suggesting -25 use).
    """
    src = f"read_parquet('{get_parquet_path()}')"

    # Detect -25 modifier abuse pattern: providers billing E&M codes alongside
    # procedure codes at unusually high rates (suggesting routine -25 modifier)
    sql = f"""
    WITH em_billing AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_CLAIMS) AS em_claims,
            SUM(TOTAL_PAID) AS em_paid,
            COUNT(DISTINCT HCPCS_CODE) AS em_codes,
            COUNT(DISTINCT CLAIM_FROM_MONTH) AS em_months
        FROM {src}
        WHERE HCPCS_CODE LIKE '9920%'
           OR HCPCS_CODE LIKE '9921%'
           OR HCPCS_CODE LIKE '9924%'
           OR HCPCS_CODE LIKE '9925%'
        GROUP BY BILLING_PROVIDER_NPI_NUM
    ),
    procedure_billing AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_CLAIMS) AS proc_claims,
            SUM(TOTAL_PAID) AS proc_paid,
            COUNT(DISTINCT HCPCS_CODE) AS proc_codes
        FROM {src}
        WHERE TRY_CAST(HCPCS_CODE AS INTEGER) IS NOT NULL
          AND CAST(HCPCS_CODE AS INTEGER) BETWEEN 10000 AND 69999
        GROUP BY BILLING_PROVIDER_NPI_NUM
    ),
    provider_total AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_CLAIMS) AS total_claims,
            SUM(TOTAL_PAID) AS total_paid
        FROM {src}
        GROUP BY BILLING_PROVIDER_NPI_NUM
    )
    SELECT
        em.npi,
        em.em_claims,
        em.em_paid,
        em.em_codes,
        em.em_months,
        COALESCE(pb.proc_claims, 0) AS proc_claims,
        COALESCE(pb.proc_paid, 0) AS proc_paid,
        pt.total_claims,
        pt.total_paid,
        em.em_claims::DOUBLE / NULLIF(pt.total_claims, 0) AS em_rate,
        COALESCE(pb.proc_claims, 0)::DOUBLE / NULLIF(em.em_claims, 0) AS proc_to_em_ratio,
        (em.em_paid + COALESCE(pb.proc_paid, 0))::DOUBLE / NULLIF(pt.total_paid, 0) AS combo_share
    FROM em_billing em
    JOIN provider_total pt ON em.npi = pt.npi
    LEFT JOIN procedure_billing pb ON em.npi = pb.npi
    WHERE em.em_claims >= 10
      AND COALESCE(pb.proc_claims, 0)::DOUBLE / NULLIF(em.em_claims, 0) > 0.4
    ORDER BY (em.em_paid + COALESCE(pb.proc_paid, 0)) DESC
    LIMIT {limit}
    """
    try:
        rows = await query_async(sql)
        results = []
        for r in rows:
            proc_to_em = float(r.get("proc_to_em_ratio", 0) or 0)
            em_rate = float(r.get("em_rate", 0) or 0)
            # Determine modifier pattern
            patterns = []
            if proc_to_em > 0.4:
                patterns.append("mod-25 (E&M + procedure combo)")
            if em_rate > 0.7:
                patterns.append("high E&M concentration")

            severity = "CRITICAL" if proc_to_em > 0.8 else ("HIGH" if proc_to_em > 0.6 else "MEDIUM")

            results.append({
                "npi": str(r["npi"]),
                "em_claims": r["em_claims"],
                "em_paid": float(r["em_paid"]),
                "proc_claims": r["proc_claims"],
                "proc_paid": float(r.get("proc_paid", 0) or 0),
                "total_claims": r["total_claims"],
                "total_paid": float(r["total_paid"]),
                "em_rate": round(em_rate, 3),
                "proc_to_em_ratio": round(proc_to_em, 3),
                "combo_share": round(float(r.get("combo_share", 0) or 0), 3),
                "modifier_patterns": patterns,
                "severity": severity,
            })
        return results
    except Exception as e:
        logger.warning("Modifier abuse detection error: %s", e)
        return []


async def detect_impossible_days(limit: int = 100) -> list[dict]:
    """
    Find providers whose monthly billing volumes imply physically impossible
    daily workloads — >50 unique beneficiaries per business day for solo
    practitioners, or implausibly high claims-per-day rates.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    sql = f"""
    WITH monthly AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            CLAIM_FROM_MONTH AS month,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS beneficiaries,
            SUM(TOTAL_CLAIMS) AS claims,
            SUM(TOTAL_PAID) AS paid,
            COUNT(DISTINCT HCPCS_CODE) AS distinct_codes
        FROM {src}
        GROUP BY BILLING_PROVIDER_NPI_NUM, CLAIM_FROM_MONTH
    ),
    impossible AS (
        SELECT
            npi,
            month,
            beneficiaries,
            claims,
            paid,
            distinct_codes,
            -- Assume ~22 business days per month
            beneficiaries::DOUBLE / 22.0 AS benes_per_day,
            claims::DOUBLE / 22.0 AS claims_per_day,
            -- Estimated hours (15 min per patient avg)
            (beneficiaries::DOUBLE / 22.0) * 0.25 AS estimated_hours_per_day
        FROM monthly
        WHERE beneficiaries::DOUBLE / 22.0 > 50
           OR claims::DOUBLE / 22.0 > 100
    ),
    provider_impossible AS (
        SELECT
            npi,
            COUNT(*) AS impossible_months,
            MAX(benes_per_day) AS max_benes_per_day,
            MAX(claims_per_day) AS max_claims_per_day,
            MAX(estimated_hours_per_day) AS max_hours_per_day,
            SUM(paid) AS impossible_paid,
            LIST(month ORDER BY benes_per_day DESC) AS worst_months
        FROM impossible
        GROUP BY npi
    ),
    provider_total AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SUM(TOTAL_PAID) AS total_paid,
            SUM(TOTAL_CLAIMS) AS total_claims,
            COUNT(DISTINCT CLAIM_FROM_MONTH) AS active_months
        FROM {src}
        GROUP BY BILLING_PROVIDER_NPI_NUM
    )
    SELECT
        pi.npi,
        pi.impossible_months,
        pi.max_benes_per_day,
        pi.max_claims_per_day,
        pi.max_hours_per_day,
        pi.impossible_paid,
        pi.worst_months,
        pt.total_paid,
        pt.total_claims,
        pt.active_months,
        pi.impossible_months::DOUBLE / NULLIF(pt.active_months, 0) AS impossible_rate
    FROM provider_impossible pi
    JOIN provider_total pt ON pi.npi = pt.npi
    ORDER BY pi.max_benes_per_day DESC
    LIMIT {limit}
    """
    try:
        rows = await query_async(sql)
        results = []
        for r in rows:
            max_benes = float(r.get("max_benes_per_day", 0) or 0)
            max_hours = float(r.get("max_hours_per_day", 0) or 0)
            worst = r.get("worst_months", [])
            if isinstance(worst, str):
                worst = [worst]

            severity = "CRITICAL" if max_benes > 100 else ("HIGH" if max_benes > 75 else "MEDIUM")

            results.append({
                "npi": str(r["npi"]),
                "impossible_months": r["impossible_months"],
                "max_benes_per_day": round(max_benes, 1),
                "max_claims_per_day": round(float(r.get("max_claims_per_day", 0) or 0), 1),
                "max_hours_per_day": round(max_hours, 1),
                "impossible_paid": float(r["impossible_paid"]),
                "worst_months": worst[:5],
                "total_paid": float(r["total_paid"]),
                "total_claims": r["total_claims"],
                "active_months": r["active_months"],
                "impossible_rate": round(float(r.get("impossible_rate", 0) or 0), 3),
                "severity": severity,
            })
        return results
    except Exception as e:
        logger.warning("Impossible day detection error: %s", e)
        return []


async def get_provider_claim_patterns(npi: str) -> dict:
    """Return all claim-level patterns for a specific provider."""
    src = f"read_parquet('{get_parquet_path()}')"

    patterns: dict[str, Any] = {
        "npi": npi,
        "unbundling": [],
        "duplicates": None,
        "pos_violations": None,
        "modifier_abuse": None,
        "impossible_days": None,
    }

    # Unbundling for this provider
    for bundle in BUNDLE_GROUPS:
        components = bundle["component_codes"]
        bundled = bundle["bundled_code"]
        comp_list = ", ".join(f"'{c}'" for c in components)
        sql = f"""
        SELECT
            COUNT(DISTINCT HCPCS_CODE) AS component_count,
            SUM(TOTAL_CLAIMS) AS component_claims,
            SUM(TOTAL_PAID) AS component_paid,
            LIST(DISTINCT HCPCS_CODE) AS codes_billed
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND HCPCS_CODE IN ({comp_list})
        """
        sql_bundled = f"""
        SELECT COALESCE(SUM(TOTAL_CLAIMS), 0) AS bundled_claims
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND HCPCS_CODE = '{bundled}'
        """
        try:
            comp_rows = await query_async(sql)
            bund_rows = await query_async(sql_bundled)
            if comp_rows and comp_rows[0]["component_count"] >= 2:
                comp = comp_rows[0]
                bund = bund_rows[0]["bundled_claims"] if bund_rows else 0
                total = comp["component_claims"] + bund
                rate = comp["component_claims"] / total if total > 0 else 0
                codes = comp.get("codes_billed", [])
                if isinstance(codes, str):
                    codes = [codes]
                patterns["unbundling"].append({
                    "bundle_name": bundle["name"],
                    "bundled_code": bundled,
                    "component_count": comp["component_count"],
                    "component_claims": comp["component_claims"],
                    "component_paid": float(comp["component_paid"]),
                    "bundled_claims": bund,
                    "unbundling_rate": round(float(rate), 3),
                    "codes_billed": codes,
                })
        except Exception:
            pass

    # Duplicates for this provider
    sql_dup = f"""
    SELECT
        HCPCS_CODE AS hcpcs_code,
        CLAIM_FROM_MONTH AS month,
        TOTAL_PAID AS paid_amount,
        COUNT(*) AS occurrence_count,
        SUM(TOTAL_CLAIMS) AS total_claims
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    GROUP BY HCPCS_CODE, CLAIM_FROM_MONTH, TOTAL_PAID
    HAVING COUNT(*) >= 2
    ORDER BY COUNT(*) DESC
    LIMIT 20
    """
    try:
        dup_rows = await query_async(sql_dup)
        patterns["duplicates"] = [{
            "hcpcs_code": r["hcpcs_code"],
            "month": r["month"],
            "paid_amount": float(r["paid_amount"]),
            "occurrence_count": r["occurrence_count"],
            "total_claims": r["total_claims"],
        } for r in dup_rows]
    except Exception:
        pass

    # Impossible days for this provider
    sql_imp = f"""
    SELECT
        CLAIM_FROM_MONTH AS month,
        SUM(TOTAL_UNIQUE_BENEFICIARIES) AS beneficiaries,
        SUM(TOTAL_CLAIMS) AS claims,
        SUM(TOTAL_PAID) AS paid,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)::DOUBLE / 22.0 AS benes_per_day,
        SUM(TOTAL_CLAIMS)::DOUBLE / 22.0 AS claims_per_day
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    GROUP BY CLAIM_FROM_MONTH
    HAVING SUM(TOTAL_UNIQUE_BENEFICIARIES)::DOUBLE / 22.0 > 50
        OR SUM(TOTAL_CLAIMS)::DOUBLE / 22.0 > 100
    ORDER BY benes_per_day DESC
    """
    try:
        imp_rows = await query_async(sql_imp)
        patterns["impossible_days"] = [{
            "month": r["month"],
            "beneficiaries": r["beneficiaries"],
            "claims": r["claims"],
            "paid": float(r["paid"]),
            "benes_per_day": round(float(r["benes_per_day"]), 1),
            "claims_per_day": round(float(r["claims_per_day"]), 1),
        } for r in imp_rows]
    except Exception:
        pass

    return patterns


async def get_summary() -> dict:
    """Return counts and totals for each pattern type."""
    unbundling = await detect_unbundling(limit=500)
    duplicates = await detect_duplicates(limit=500)
    pos_violations = await detect_pos_violations(limit=500)
    modifiers = await detect_modifier_abuse(limit=500)
    impossible = await detect_impossible_days(limit=500)

    def severity_counts(items: list[dict]) -> dict:
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
        for item in items:
            sev = item.get("severity", "MEDIUM")
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    return {
        "unbundling": {
            "count": len(unbundling),
            "total_paid": sum(r.get("component_paid", 0) for r in unbundling),
            "severity_counts": severity_counts(unbundling),
        },
        "duplicates": {
            "count": len(duplicates),
            "total_paid": sum(r.get("duplicate_paid", 0) for r in duplicates),
            "severity_counts": severity_counts(duplicates),
        },
        "pos_violations": {
            "count": len(pos_violations),
            "total_paid": sum(r.get("surgical_paid", 0) for r in pos_violations),
            "severity_counts": severity_counts(pos_violations),
        },
        "modifier_abuse": {
            "count": len(modifiers),
            "total_paid": sum(r.get("total_paid", 0) for r in modifiers),
            "severity_counts": severity_counts(modifiers),
        },
        "impossible_days": {
            "count": len(impossible),
            "total_paid": sum(r.get("impossible_paid", 0) for r in impossible),
            "severity_counts": severity_counts(impossible),
        },
        "total_patterns": len(unbundling) + len(duplicates) + len(pos_violations) + len(modifiers) + len(impossible),
    }
