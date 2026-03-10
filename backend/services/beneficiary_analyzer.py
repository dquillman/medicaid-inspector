"""
Beneficiary-level fraud detection — analyses aggregate Parquet data to
surface provider-level patterns that indicate beneficiary fraud:

1. Doctor shopping proxy: providers whose beneficiaries also appear at many
   other providers billing the same HCPCS codes (high shared-beneficiary overlap
   with many distinct NPIs on the same codes).
2. High utilization: providers with abnormally high beneficiary-to-provider
   ratios or claims-per-beneficiary vs. peers.
3. Geographic impossibility proxy: providers billing from multiple states or
   servicing NPIs spread across distant states.
4. Excessive services: providers whose service-line counts per beneficiary
   far exceed peer medians.

Since the Parquet data is aggregate (no individual BENE_ID), we use
statistical proxies that surface the same patterns an investigator would
look for in beneficiary-level claims data.
"""
import logging
import statistics
from collections import defaultdict

from data.duckdb_client import query_async, get_parquet_path

log = logging.getLogger(__name__)


async def _check_bene_id_column() -> bool:
    """Return True if the Parquet data has a BENE_ID column."""
    src = f"read_parquet('{get_parquet_path()}')"
    try:
        rows = await query_async(f"""
            SELECT column_name
            FROM (DESCRIBE SELECT * FROM {src} LIMIT 0)
            WHERE lower(column_name) IN ('bene_id', 'beneficiary_id', 'msis_id')
            LIMIT 1
        """)
        return len(rows) > 0
    except Exception:
        return False


async def _get_available_columns() -> set[str]:
    """Return the set of available column names (lowercased)."""
    src = f"read_parquet('{get_parquet_path()}')"
    try:
        rows = await query_async(f"""
            SELECT column_name
            FROM (DESCRIBE SELECT * FROM {src} LIMIT 0)
        """)
        return {r["column_name"].lower() for r in rows}
    except Exception:
        return set()


# ── Doctor Shopping Proxy ───────────────────────────────────────────────────

async def detect_doctor_shopping(limit: int = 100) -> dict:
    """
    Identify providers whose patients likely doctor-shop by finding NPIs
    that share HCPCS codes with an unusually high number of other billing NPIs
    for the same codes, weighted by beneficiary volume.

    Logic: For each HCPCS code, count how many distinct billing NPIs use it.
    Providers whose top codes are billed by many other NPIs AND who have
    high claims-per-beneficiary are flagged — their beneficiaries are likely
    seeing multiple providers for the same service.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    try:
        rows = await query_async(f"""
            WITH code_popularity AS (
                SELECT
                    HCPCS_CODE,
                    COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM) AS npi_count
                FROM {src}
                GROUP BY HCPCS_CODE
                HAVING COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM) >= 5
            ),
            provider_codes AS (
                SELECT
                    p.BILLING_PROVIDER_NPI_NUM AS npi,
                    p.HCPCS_CODE,
                    SUM(p.TOTAL_PAID) AS code_paid,
                    SUM(p.TOTAL_CLAIMS) AS code_claims,
                    SUM(p.TOTAL_UNIQUE_BENEFICIARIES) AS code_benes,
                    cp.npi_count AS competing_providers
                FROM {src} p
                JOIN code_popularity cp ON p.HCPCS_CODE = cp.HCPCS_CODE
                GROUP BY p.BILLING_PROVIDER_NPI_NUM, p.HCPCS_CODE, cp.npi_count
            ),
            provider_risk AS (
                SELECT
                    npi,
                    COUNT(DISTINCT HCPCS_CODE) AS shared_code_count,
                    MAX(competing_providers) AS max_competing_providers,
                    AVG(competing_providers) AS avg_competing_providers,
                    SUM(code_paid) AS total_paid,
                    SUM(code_claims) AS total_claims,
                    SUM(code_benes) AS total_benes,
                    CAST(SUM(code_claims) AS DOUBLE) /
                        NULLIF(SUM(code_benes), 0) AS claims_per_bene
                FROM provider_codes
                WHERE competing_providers >= 10
                GROUP BY npi
                HAVING SUM(code_benes) > 0
            )
            SELECT *,
                CAST(claims_per_bene * avg_competing_providers AS DOUBLE) AS shopping_score
            FROM provider_risk
            ORDER BY shopping_score DESC
            LIMIT {limit}
        """)
        return {
            "flagged": rows,
            "total_flagged": len(rows),
            "note": "Providers whose patients likely see many other providers for the same services"
        }
    except Exception as e:
        log.error("Doctor shopping detection failed: %s", e)
        return {"flagged": [], "total_flagged": 0, "error": str(e)}


# ── High Utilization ────────────────────────────────────────────────────────

async def detect_high_utilization(limit: int = 100) -> dict:
    """
    Find providers where beneficiaries have abnormally high utilization:
    claims-per-beneficiary and revenue-per-beneficiary far exceeding peers
    billing the same top HCPCS code.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    try:
        rows = await query_async(f"""
            WITH provider_agg AS (
                SELECT
                    BILLING_PROVIDER_NPI_NUM AS npi,
                    SUM(TOTAL_PAID) AS total_paid,
                    SUM(TOTAL_CLAIMS) AS total_claims,
                    SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
                    COUNT(DISTINCT HCPCS_CODE) AS distinct_hcpcs,
                    CAST(SUM(TOTAL_CLAIMS) AS DOUBLE) /
                        NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS claims_per_bene,
                    CAST(SUM(TOTAL_PAID) AS DOUBLE) /
                        NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS rev_per_bene
                FROM {src}
                GROUP BY BILLING_PROVIDER_NPI_NUM
                HAVING SUM(TOTAL_UNIQUE_BENEFICIARIES) > 0
            ),
            stats AS (
                SELECT
                    AVG(claims_per_bene) AS mean_cpb,
                    STDDEV_SAMP(claims_per_bene) AS std_cpb,
                    AVG(rev_per_bene) AS mean_rpb,
                    STDDEV_SAMP(rev_per_bene) AS std_rpb,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY claims_per_bene) AS median_cpb,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY claims_per_bene) AS p90_cpb,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rev_per_bene) AS median_rpb,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY rev_per_bene) AS p90_rpb
                FROM provider_agg
            )
            SELECT
                p.npi,
                p.total_paid,
                p.total_claims,
                p.total_benes,
                p.distinct_hcpcs,
                ROUND(p.claims_per_bene, 2) AS claims_per_bene,
                ROUND(p.rev_per_bene, 2) AS rev_per_bene,
                ROUND((p.claims_per_bene - s.mean_cpb) / NULLIF(s.std_cpb, 0), 2) AS cpb_z_score,
                ROUND((p.rev_per_bene - s.mean_rpb) / NULLIF(s.std_rpb, 0), 2) AS rpb_z_score,
                ROUND(s.median_cpb, 2) AS peer_median_cpb,
                ROUND(s.p90_cpb, 2) AS peer_p90_cpb,
                ROUND(s.median_rpb, 2) AS peer_median_rpb,
                ROUND(s.p90_rpb, 2) AS peer_p90_rpb
            FROM provider_agg p
            CROSS JOIN stats s
            WHERE p.claims_per_bene > s.p90_cpb
               OR p.rev_per_bene > s.p90_rpb
            ORDER BY (p.claims_per_bene - s.mean_cpb) / NULLIF(s.std_cpb, 0) +
                     (p.rev_per_bene - s.mean_rpb) / NULLIF(s.std_rpb, 0) DESC
            LIMIT {limit}
        """)
        return {
            "flagged": rows,
            "total_flagged": len(rows),
            "note": "Providers whose beneficiaries have abnormally high claims/revenue per beneficiary"
        }
    except Exception as e:
        log.error("High utilization detection failed: %s", e)
        return {"flagged": [], "total_flagged": 0, "error": str(e)}


# ── Geographic Impossibility Proxy ──────────────────────────────────────────

async def detect_geographic_anomalies(limit: int = 100) -> dict:
    """
    Detect providers with servicing NPIs in multiple distant states or
    billing from multiple states — proxy for beneficiaries receiving services
    in geographically impossible locations.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    cols = await _get_available_columns()

    # Check if we have servicing NPI and state columns
    has_servicing = "servicing_provider_npi_num" in cols
    has_state = any(c for c in cols if "state" in c)

    if not has_servicing:
        return {
            "flagged": [],
            "total_flagged": 0,
            "note": "No SERVICING_PROVIDER_NPI_NUM column available for geographic analysis"
        }

    # Find the state column name
    state_col = None
    for candidate in ["billing_provider_state", "prvdr_state_abrvtn", "nppes_provider_state"]:
        if candidate in cols:
            state_col = candidate
            break
    if not state_col:
        for c in cols:
            if "state" in c and "zip" not in c:
                state_col = c
                break

    if not state_col:
        return {
            "flagged": [],
            "total_flagged": 0,
            "note": "No state column available for geographic analysis"
        }

    try:
        rows = await query_async(f"""
            WITH provider_states AS (
                SELECT
                    BILLING_PROVIDER_NPI_NUM AS npi,
                    COUNT(DISTINCT {state_col}) AS state_count,
                    COUNT(DISTINCT SERVICING_PROVIDER_NPI_NUM) AS servicing_npi_count,
                    LIST(DISTINCT {state_col}) AS states,
                    SUM(TOTAL_PAID) AS total_paid,
                    SUM(TOTAL_CLAIMS) AS total_claims,
                    SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes
                FROM {src}
                GROUP BY BILLING_PROVIDER_NPI_NUM
                HAVING COUNT(DISTINCT {state_col}) >= 2
            )
            SELECT
                npi,
                state_count,
                servicing_npi_count,
                states,
                total_paid,
                total_claims,
                total_benes,
                state_count * servicing_npi_count AS geo_risk_score
            FROM provider_states
            ORDER BY geo_risk_score DESC
            LIMIT {limit}
        """)
        # Convert list columns to strings for JSON serialization
        for r in rows:
            if isinstance(r.get("states"), list):
                r["states"] = r["states"]
        return {
            "flagged": rows,
            "total_flagged": len(rows),
            "note": "Providers billing from multiple states — possible geographic impossibility"
        }
    except Exception as e:
        log.error("Geographic anomaly detection failed: %s", e)
        return {"flagged": [], "total_flagged": 0, "error": str(e)}


# ── Excessive Services ──────────────────────────────────────────────────────

async def detect_excessive_services(limit: int = 100) -> dict:
    """
    Find providers with abnormally high total service line counts
    per beneficiary vs. peer median — proxy for beneficiaries receiving
    excessive services.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    cols = await _get_available_columns()

    # Try to use LINE_SRVC_CNT if available, otherwise fall back to TOTAL_CLAIMS
    service_col = "TOTAL_CLAIMS"
    for c in cols:
        if "line_srvc" in c or "srvc_cnt" in c:
            service_col = c.upper()
            break

    try:
        rows = await query_async(f"""
            WITH provider_svc AS (
                SELECT
                    BILLING_PROVIDER_NPI_NUM AS npi,
                    SUM({service_col}) AS total_services,
                    SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
                    SUM(TOTAL_PAID) AS total_paid,
                    COUNT(DISTINCT HCPCS_CODE) AS distinct_hcpcs,
                    COUNT(DISTINCT CLAIM_FROM_MONTH) AS active_months,
                    CAST(SUM({service_col}) AS DOUBLE) /
                        NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS svc_per_bene
                FROM {src}
                GROUP BY BILLING_PROVIDER_NPI_NUM
                HAVING SUM(TOTAL_UNIQUE_BENEFICIARIES) > 0
            ),
            stats AS (
                SELECT
                    AVG(svc_per_bene) AS mean_spb,
                    STDDEV_SAMP(svc_per_bene) AS std_spb,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY svc_per_bene) AS median_spb,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY svc_per_bene) AS p90_spb,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY svc_per_bene) AS p95_spb
                FROM provider_svc
            )
            SELECT
                p.npi,
                p.total_services,
                p.total_benes,
                p.total_paid,
                p.distinct_hcpcs,
                p.active_months,
                ROUND(p.svc_per_bene, 2) AS svc_per_bene,
                ROUND((p.svc_per_bene - s.mean_spb) / NULLIF(s.std_spb, 0), 2) AS z_score,
                ROUND(s.median_spb, 2) AS peer_median,
                ROUND(s.p90_spb, 2) AS peer_p90,
                ROUND(s.p95_spb, 2) AS peer_p95,
                ROUND(p.svc_per_bene / NULLIF(s.median_spb, 0), 2) AS multiple_of_median
            FROM provider_svc p
            CROSS JOIN stats s
            WHERE p.svc_per_bene > s.p90_spb
            ORDER BY p.svc_per_bene DESC
            LIMIT {limit}
        """)
        return {
            "flagged": rows,
            "total_flagged": len(rows),
            "service_column_used": service_col,
            "note": "Providers with services-per-beneficiary exceeding the 90th percentile"
        }
    except Exception as e:
        log.error("Excessive services detection failed: %s", e)
        return {"flagged": [], "total_flagged": 0, "error": str(e)}


# ── Summary ─────────────────────────────────────────────────────────────────

async def beneficiary_fraud_summary() -> dict:
    """
    High-level summary stats: total providers analyzed, counts flagged by each
    detection method.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    has_bene_id = await _check_bene_id_column()

    try:
        basic = await query_async(f"""
            SELECT
                COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM) AS total_providers,
                SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_beneficiary_records,
                SUM(TOTAL_PAID) AS total_paid,
                SUM(TOTAL_CLAIMS) AS total_claims
            FROM {src}
        """)
        base = basic[0] if basic else {}
    except Exception as e:
        base = {"error": str(e)}

    # Run all detections to get counts (with small limits for speed)
    shopping = await detect_doctor_shopping(limit=200)
    utilization = await detect_high_utilization(limit=200)
    geographic = await detect_geographic_anomalies(limit=200)
    excessive = await detect_excessive_services(limit=200)

    return {
        "total_providers_analyzed": base.get("total_providers", 0),
        "total_beneficiary_records": base.get("total_beneficiary_records", 0),
        "total_paid": base.get("total_paid", 0),
        "has_individual_bene_id": has_bene_id,
        "flagged_counts": {
            "doctor_shopping": shopping.get("total_flagged", 0),
            "high_utilization": utilization.get("total_flagged", 0),
            "geographic_anomalies": geographic.get("total_flagged", 0),
            "excessive_services": excessive.get("total_flagged", 0),
        },
        "note": (
            "Analysis uses aggregate provider data as proxy for beneficiary-level patterns. "
            "Individual BENE_ID column " +
            ("is available for future granular analysis." if has_bene_id
             else "is not present — results are statistical proxies based on provider aggregates.")
        ),
    }


# ── Provider-Specific Beneficiary Fraud ─────────────────────────────────────

async def provider_beneficiary_fraud(npi: str) -> dict:
    """
    Analyze beneficiary fraud patterns linked to a specific provider's panel.
    """
    src = f"read_parquet('{get_parquet_path()}')"

    try:
        # Basic provider stats
        provider_stats = await query_async(f"""
            SELECT
                BILLING_PROVIDER_NPI_NUM AS npi,
                SUM(TOTAL_PAID) AS total_paid,
                SUM(TOTAL_CLAIMS) AS total_claims,
                SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_benes,
                COUNT(DISTINCT HCPCS_CODE) AS distinct_hcpcs,
                COUNT(DISTINCT CLAIM_FROM_MONTH) AS active_months,
                CAST(SUM(TOTAL_CLAIMS) AS DOUBLE) /
                    NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS claims_per_bene,
                CAST(SUM(TOTAL_PAID) AS DOUBLE) /
                    NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS rev_per_bene
            FROM {src}
            WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
            GROUP BY BILLING_PROVIDER_NPI_NUM
        """)

        if not provider_stats:
            return {"npi": npi, "found": False, "note": "Provider not found in dataset"}

        prov = provider_stats[0]

        # Get peer stats for comparison
        peer_stats = await query_async(f"""
            WITH provider_agg AS (
                SELECT
                    BILLING_PROVIDER_NPI_NUM AS npi,
                    CAST(SUM(TOTAL_CLAIMS) AS DOUBLE) /
                        NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS claims_per_bene,
                    CAST(SUM(TOTAL_PAID) AS DOUBLE) /
                        NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS rev_per_bene,
                    CAST(SUM(TOTAL_CLAIMS) AS DOUBLE) /
                        NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS svc_per_bene
                FROM {src}
                GROUP BY BILLING_PROVIDER_NPI_NUM
                HAVING SUM(TOTAL_UNIQUE_BENEFICIARIES) > 0
            )
            SELECT
                ROUND(AVG(claims_per_bene), 2) AS mean_cpb,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY claims_per_bene), 2) AS median_cpb,
                ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY claims_per_bene), 2) AS p90_cpb,
                ROUND(AVG(rev_per_bene), 2) AS mean_rpb,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rev_per_bene), 2) AS median_rpb,
                ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY rev_per_bene), 2) AS p90_rpb,
                COUNT(*) AS peer_count
            FROM provider_agg
        """)
        peers = peer_stats[0] if peer_stats else {}

        # Check code overlap (doctor shopping proxy)
        code_overlap = await query_async(f"""
            WITH provider_codes AS (
                SELECT DISTINCT HCPCS_CODE
                FROM {src}
                WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
            ),
            code_sharing AS (
                SELECT
                    pc.HCPCS_CODE,
                    COUNT(DISTINCT d.BILLING_PROVIDER_NPI_NUM) AS other_providers
                FROM provider_codes pc
                JOIN {src} d ON d.HCPCS_CODE = pc.HCPCS_CODE
                WHERE d.BILLING_PROVIDER_NPI_NUM != '{npi}'
                GROUP BY pc.HCPCS_CODE
            )
            SELECT
                HCPCS_CODE AS hcpcs_code,
                other_providers
            FROM code_sharing
            ORDER BY other_providers DESC
            LIMIT 10
        """)

        # Determine risk flags
        flags = []
        cpb = prov.get("claims_per_bene") or 0
        rpb = prov.get("rev_per_bene") or 0
        p90_cpb = peers.get("p90_cpb") or 0
        p90_rpb = peers.get("p90_rpb") or 0

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
                "total_paid": prov.get("total_paid", 0),
                "total_claims": prov.get("total_claims", 0),
                "total_benes": prov.get("total_benes", 0),
                "distinct_hcpcs": prov.get("distinct_hcpcs", 0),
                "active_months": prov.get("active_months", 0),
                "claims_per_bene": round(cpb, 2),
                "rev_per_bene": round(rpb, 2),
            },
            "peer_comparison": peers,
            "code_overlap": code_overlap,
            "flags": flags,
            "flag_count": len(flags),
        }
    except Exception as e:
        log.error("Provider beneficiary fraud analysis failed for %s: %s", npi, e)
        return {"npi": npi, "found": False, "error": str(e)}
