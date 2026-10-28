"""Live scoring using the same detector runner and full-dataset cohorts as scans."""
from __future__ import annotations
import asyncio
import time
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit
from pathlib import Path
from data.duckdb_client import query_async, get_parquet_path
from services.anomaly_detector import compute_address_clusters, compute_auth_official_clusters


async def score_provider(npi: str, provider_agg: dict) -> dict:
    """
    Run all anomaly detectors for a single NPI.
    Returns {risk_score, flags, signal_results}.
    provider_agg must be a row from provider_aggregate_sql.
    """
    # Fetch supporting data in parallel — use parameterized queries
    hcpcs_sql, hcpcs_params = _hcpcs_sql(npi)
    timeline_sql, timeline_params = _timeline_sql(npi)
    hcpcs_rows, timeline_rows, cohort = await asyncio.gather(
        query_async(hcpcs_sql, hcpcs_params),
        query_async(timeline_sql, timeline_params),
        canonical_cohort_stats(),
    )
    peer_stats, cpb_stats, spend_mean, spend_std = cohort

    # Pre-compute cluster sizes from prescan cache
    cluster_sizes = compute_address_clusters()
    auth_clusters = compute_auth_official_clusters()

    from services.scan_engine import _score_provider, _import_signals
    top_code = hcpcs_rows[0]["hcpcs_code"] if hcpcs_rows else ""
    result = _score_provider(
        provider_agg, hcpcs_rows, timeline_rows, npi, top_code,
        peer_stats, cpb_stats, spend_mean, spend_std,
        cluster_sizes, auth_clusters, _import_signals(),
    )
    return {key: result.get(key) for key in ("risk_score", "flags", "signal_results", "scoring_metadata")}


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
    ORDER BY total_paid DESC, hcpcs_code ASC
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


SCORING_SPEC_VERSION = "shared-15-detectors-aggregate-denominator-v2-code-system-guard"
COHORT_SPEC_VERSION = "dominant-code-whole-provider-v1"
COHORT_CACHE_TTL_SECONDS = 300
_cohort_cache = None
_last_cohort_result = None
_cohort_observation = {"status": "unknown", "reason": "No canonical source snapshot recorded"}


def _cohort_source_identity(source: str):
    """Local replacement/edits invalidate immediately; unversioned URLs never cache.

    This identifies the input snapshot, not upstream freshness. Remote URLs
    without immutable generations cannot safely establish a source version.
    """
    if "://" in source:
        return None
    try:
        stat = Path(source).stat()
    except OSError:
        return None
    return (str(Path(source).resolve()), stat.st_size, stat.st_mtime_ns,
            stat.st_ctime_ns, stat.st_ino, COHORT_SPEC_VERSION)


def _public_source_observation(source, identity):
    name = Path(urlsplit(source).path).name if "://" in source else Path(source).name
    return {
        "name": name,
        "identity_kind": "local_file_stat_fingerprint" if identity is not None else "unversioned_remote_or_unavailable",
        "identity": hashlib.sha256(repr(identity).encode()).hexdigest() if identity is not None else None,
        "content_checksum": None,
        "upstream_freshness": "unknown",
    }


def cohort_observation(top_code=None, rpb=None, cpb=None, spend=None):
    """Evidence about the last cohort query; absent legacy metadata stays unknown."""
    from copy import deepcopy
    if top_code is not None and (
            _last_cohort_result is None
            or _last_cohort_result[0].get(top_code, (0.0, 0.0)) != rpb
            or _last_cohort_result[1].get(top_code, (0.0, 0.0)) != cpb
            or _last_cohort_result[2:] != spend):
        return {"status": "unknown", "reason": "Supplied cohort statistics do not match the recorded canonical query"}
    return deepcopy(_cohort_observation)


def _copy_cohort(cohort):
    return dict(cohort[0]), dict(cohort[1]), cohort[2], cohort[3]


async def canonical_cohort_stats():
    """Whole-provider ratios grouped by dominant code across the entire source.

    Never depends on scan order, cache contents, or selected batch. Missing or
    sparse cohorts remain unavailable instead of using unrelated specialties.
    """
    global _cohort_cache, _cohort_observation, _last_cohort_result
    source = get_parquet_path()
    identity = _cohort_source_identity(source)
    now = time.monotonic()
    if (identity is not None and _cohort_cache is not None
            and _cohort_cache[0] == identity
            and now - _cohort_cache[1] < COHORT_CACHE_TTL_SECONDS):
        _cohort_observation = dict(_cohort_cache[3])
        _last_cohort_result = _copy_cohort(_cohort_cache[2])
        return _copy_cohort(_cohort_cache[2])
    src = f"read_parquet('{source}')"
    rows = await query_async(f"""
        WITH code_totals AS (
            SELECT BILLING_PROVIDER_NPI_NUM AS npi, HCPCS_CODE AS code,
                   SUM(TOTAL_PAID) AS paid
            FROM {src} GROUP BY 1, 2
        ), dominant AS (
            SELECT npi, code, ROW_NUMBER() OVER (
                PARTITION BY npi ORDER BY paid DESC, code ASC) AS rank
            FROM code_totals
        ), providers AS (
            SELECT BILLING_PROVIDER_NPI_NUM AS npi,
                   SUM(TOTAL_PAID) AS spend,
                   SUM(TOTAL_PAID)::DOUBLE / NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS rpb,
                   SUM(TOTAL_CLAIMS)::DOUBLE / NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0) AS cpb
            FROM {src} GROUP BY 1
        )
        SELECT d.code,
            AVG(p.rpb) FILTER (WHERE p.rpb > 0) AS mean_rpb,
            STDDEV_SAMP(p.rpb) FILTER (WHERE p.rpb > 0) AS std_rpb,
            COUNT(*) FILTER (WHERE p.rpb > 0) AS n_rpb,
            AVG(p.cpb) FILTER (WHERE p.cpb > 0) AS mean_cpb,
            STDDEV_SAMP(p.cpb) FILTER (WHERE p.cpb > 0) AS std_cpb,
            COUNT(*) FILTER (WHERE p.cpb > 0) AS n_cpb,
            (SELECT AVG(spend) FROM providers WHERE spend > 0) AS mean_spend,
            (SELECT STDDEV_SAMP(spend) FROM providers WHERE spend > 0) AS std_spend
        FROM providers p JOIN dominant d ON p.npi = d.npi AND d.rank = 1
        GROUP BY d.code
    """)
    rpb = {r["code"]: (float(r["mean_rpb"] or 0), float(r["std_rpb"] or 0))
           for r in rows if r["n_rpb"] >= 3}
    cpb = {r["code"]: (float(r["mean_cpb"] or 0), float(r["std_cpb"] or 0))
           for r in rows if r["n_cpb"] >= 3}
    first = rows[0] if rows else {}
    result = (rpb, cpb, float(first.get("mean_spend") or 0), float(first.get("std_spend") or 0))
    unchanged = identity is not None and _cohort_source_identity(source) == identity
    _cohort_observation = {
        "status": "local_snapshot_recorded" if unchanged else "source_version_unknown",
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "source": _public_source_observation(source, identity if unchanged else None),
        "scope": "whole source; grouped by dominant HCPCS; all billing periods present in source",
        "coverage_verified": False,
    }
    _last_cohort_result = _copy_cohort(result)
    # Do not cache a query whose source was replaced while it ran.
    if unchanged:
        _cohort_cache = (identity, time.monotonic(), _copy_cohort(result), dict(_cohort_observation))
    return result
