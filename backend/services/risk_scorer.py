"""
Composite risk scorer.
Fetches all required data for a provider from DuckDB, runs all 17 detectors,
and returns a composite score (0–100) + list of active flags.
"""
from __future__ import annotations
import asyncio
import math
from data.duckdb_client import query_async, get_parquet_path
from services.anomaly_detector import (
    billing_concentration,
    revenue_per_bene_outlier,
    claims_per_bene_anomaly,
    billing_ramp_rate,
    bust_out_pattern,
    ghost_billing,
    bene_concentration,
    upcoding_pattern,
    address_cluster_risk,
    oig_excluded,
    compute_address_clusters,
    specialty_mismatch,
    corporate_shell_risk,
    compute_auth_official_clusters,
    dead_npi_billing,
    new_provider_explosion,
    geographic_impossibility,
    SignalResult,
)


async def score_provider(npi: str, provider_agg: dict) -> dict:
    """
    Run all anomaly detectors for a single NPI.
    Returns {risk_score, flags, signal_results}.
    provider_agg must be a row from provider_aggregate_sql.
    """
    # Fetch supporting data in parallel — use parameterized queries
    hcpcs_sql, hcpcs_params = _hcpcs_sql(npi)
    timeline_sql, timeline_params = _timeline_sql(npi)
    peer_sql, peer_params = _peer_stats_sql(npi)
    hcpcs_task = query_async(hcpcs_sql, hcpcs_params)
    timeline_task = query_async(timeline_sql, timeline_params)
    peer_task = query_async(peer_sql, peer_params)

    hcpcs_rows, timeline_rows, peer_rows = await asyncio.gather(
        hcpcs_task, timeline_task, peer_task
    )

    peer = peer_rows[0] if peer_rows else {}
    peer_mean = float(peer.get("mean_rpb") or 0)
    peer_std = float(peer.get("std_rpb") or 0)

    # Pre-compute cluster sizes from prescan cache
    cluster_sizes = compute_address_clusters()
    auth_clusters = compute_auth_official_clusters()

    signals: list[SignalResult] = [
        billing_concentration(provider_agg, hcpcs_rows),
        revenue_per_bene_outlier(provider_agg, peer_mean, peer_std),
        claims_per_bene_anomaly(provider_agg),
        billing_ramp_rate(timeline_rows),
        bust_out_pattern(timeline_rows),
        ghost_billing(provider_agg, timeline_rows),
        bene_concentration(provider_agg),
        upcoding_pattern(provider_agg, hcpcs_rows),
        address_cluster_risk(provider_agg, cluster_sizes.get(npi, 0)),
        oig_excluded(npi),
        specialty_mismatch(provider_agg, hcpcs_rows),
        corporate_shell_risk(provider_agg, auth_clusters.get(npi, 0)),
        dead_npi_billing(provider_agg),
        new_provider_explosion(provider_agg),
        geographic_impossibility(provider_agg),
    ]

    composite = sum(s["score"] * s["weight"] for s in signals)
    risk_score = min(round(composite, 1), 100.0)
    flags = [s for s in signals if s["flagged"]]

    return {
        "risk_score": risk_score,
        "flags": flags,
        "signal_results": signals,
    }


async def batch_score(npis: list[str], provider_aggs: list[dict]) -> list[dict]:
    """Score multiple providers concurrently (used for prescan)."""
    tasks = [score_provider(p["npi"], p) for p in provider_aggs]
    return await asyncio.gather(*tasks)


# ── NPI validation ────────────────────────────────────────────────────────────
import re as _re

_NPI_RE = _re.compile(r"^\d{10}$")


def _validate_npi(npi: str) -> str:
    """
    Validate that npi is exactly 10 digits.
    Raises ValueError on invalid input — prevents SQL injection via NPI parameter.
    """
    if not isinstance(npi, str) or not _NPI_RE.match(npi):
        raise ValueError(f"Invalid NPI format (must be 10 digits): {npi!r}")
    return npi


# ── SQL helpers ───────────────────────────────────────────────────────────────
def _hcpcs_sql(npi: str) -> tuple[str, tuple]:
    """Return (sql, params) for HCPCS breakdown query — uses parameterized query."""
    _validate_npi(npi)
    src = f"read_parquet('{get_parquet_path()}')"
    sql = f"""
    SELECT
        HCPCS_CODE          AS hcpcs_code,
        SUM(TOTAL_PAID)     AS total_paid,
        SUM(TOTAL_CLAIMS)   AS total_claims
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = ?
    GROUP BY HCPCS_CODE
    ORDER BY total_paid DESC
    LIMIT 50
    """
    return sql, (npi,)


def _timeline_sql(npi: str) -> tuple[str, tuple]:
    """Return (sql, params) for monthly timeline query — uses parameterized query."""
    _validate_npi(npi)
    src = f"read_parquet('{get_parquet_path()}')"
    sql = f"""
    SELECT
        CLAIM_FROM_MONTH                    AS month,
        SUM(TOTAL_PAID)                     AS total_paid,
        SUM(TOTAL_CLAIMS)                   AS total_claims,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS total_unique_beneficiaries
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = ?
    GROUP BY CLAIM_FROM_MONTH
    ORDER BY CLAIM_FROM_MONTH ASC
    """
    return sql, (npi,)


def _peer_stats_sql(npi: str) -> tuple[str, tuple]:
    """
    Compute mean and std of revenue_per_beneficiary for providers
    sharing the same top HCPCS code as this NPI.
    Uses parameterized query to prevent SQL injection.
    """
    _validate_npi(npi)
    src = f"read_parquet('{get_parquet_path()}')"
    sql = f"""
    WITH this_top AS (
        SELECT HCPCS_CODE
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = ?
        GROUP BY HCPCS_CODE
        ORDER BY SUM(TOTAL_PAID) DESC
        LIMIT 1
    ),
    peers AS (
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            CAST(SUM(TOTAL_PAID) AS DOUBLE) /
                NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS rpb
        FROM {src}
        WHERE HCPCS_CODE = (SELECT HCPCS_CODE FROM this_top)
        GROUP BY BILLING_PROVIDER_NPI_NUM
    )
    SELECT
        AVG(rpb) AS mean_rpb,
        STDDEV(rpb) AS std_rpb
    FROM peers
    """
    return sql, (npi,)
