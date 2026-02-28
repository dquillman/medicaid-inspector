"""
Composite risk scorer.
Fetches all required data for a provider from DuckDB, runs all 6 detectors,
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
    SignalResult,
)


async def score_provider(npi: str, provider_agg: dict) -> dict:
    """
    Run all anomaly detectors for a single NPI.
    Returns {risk_score, flags, signal_results}.
    provider_agg must be a row from provider_aggregate_sql.
    """
    # Fetch supporting data in parallel
    hcpcs_task = query_async(_hcpcs_sql(npi))
    timeline_task = query_async(_timeline_sql(npi))
    peer_task = query_async(_peer_stats_sql(npi))

    hcpcs_rows, timeline_rows, peer_rows = await asyncio.gather(
        hcpcs_task, timeline_task, peer_task
    )

    peer = peer_rows[0] if peer_rows else {}
    peer_mean = float(peer.get("mean_rpb") or 0)
    peer_std = float(peer.get("std_rpb") or 0)

    signals: list[SignalResult] = [
        billing_concentration(provider_agg, hcpcs_rows),
        revenue_per_bene_outlier(provider_agg, peer_mean, peer_std),
        claims_per_bene_anomaly(provider_agg),
        billing_ramp_rate(timeline_rows),
        bust_out_pattern(timeline_rows),
        ghost_billing(provider_agg, timeline_rows),
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


# ── SQL helpers ───────────────────────────────────────────────────────────────
def _hcpcs_sql(npi: str) -> str:
    src = f"read_parquet('{get_parquet_path()}')"
    return f"""
    SELECT
        HCPCS_CODE          AS hcpcs_code,
        SUM(TOTAL_PAID)     AS total_paid,
        SUM(TOTAL_CLAIMS)   AS total_claims
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    GROUP BY HCPCS_CODE
    ORDER BY total_paid DESC
    LIMIT 50
    """


def _timeline_sql(npi: str) -> str:
    src = f"read_parquet('{get_parquet_path()}')"
    return f"""
    SELECT
        CLAIM_FROM_MONTH                    AS month,
        SUM(TOTAL_PAID)                     AS total_paid,
        SUM(TOTAL_CLAIMS)                   AS total_claims,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS total_unique_beneficiaries
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    GROUP BY CLAIM_FROM_MONTH
    ORDER BY CLAIM_FROM_MONTH ASC
    """


def _peer_stats_sql(npi: str) -> str:
    """
    Compute mean and std of revenue_per_beneficiary for providers
    sharing the same top HCPCS code as this NPI.
    """
    src = f"read_parquet('{get_parquet_path()}')"
    return f"""
    WITH this_top AS (
        SELECT HCPCS_CODE
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
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
