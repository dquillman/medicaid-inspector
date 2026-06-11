"""
Slim-cache enrichment helper.

The Cloud Run slim prescan cache deliberately omits per-HCPCS and
per-timeline arrays to stay at ~59 MB. Routes that need that detail
(billing-code analysis, claim patterns, pharmacy/DME) call into here to
batch-fetch the data for the top-N riskiest providers from the Parquet
dataset via DuckDB, then stitch it onto the slim metadata.

The cost is two batched aggregations per call; results are not cached
here — callers wrap them in their own response cache.
"""
from __future__ import annotations

import logging
import time

from core.store import get_prescanned

logger = logging.getLogger(__name__)

# Cap how many providers we enrich per call. The two batched Parquet
# aggregations are O(rows in result), so picking the riskiest 500 keeps
# the query envelope bounded and the latency reasonable.
DEFAULT_TOPN = 500


def parquet_is_local() -> bool:
    """True when the DuckDB parquet source is a local file.

    The enrichment queries below are fine against a local parquet (~seconds)
    but run 60-300s against the remote 2.94 GB parquet over httpfs — long
    enough to trip the Cloud Run request timeout. Callers on the slim-cache
    path must check this before calling enrich_top_providers and short-circuit
    with a "requires full cache" note when the parquet is remote (same
    pattern as the v3.1.5 beneficiary-fraud fix).
    """
    from data.duckdb_client import get_parquet_path
    path = str(get_parquet_path())
    return not path.startswith(("http://", "https://", "s3://", "gs://", "az://", "abfss://"))


SLIM_REMOTE_NOTE = (
    "This analysis requires per-claim HCPCS detail, which is only present in the "
    "full prescan cache. The server is running on the slim cache with a remote "
    "dataset, so computing it live would exceed the request timeout. Run a fresh "
    "scan or restore the full cache from GCS to enable it."
)


def has_hcpcs_detail(sample_size: int = 200) -> bool:
    """True if the loaded prescan cache carries per-HCPCS arrays (full cache).

    Used by routes to choose between the in-memory path (full cache) and the
    DuckDB enrichment path (slim cache).
    """
    for p in get_prescanned()[:sample_size]:
        if p.get("hcpcs"):
            return True
    return False


def enrich_top_providers(top_n: int = DEFAULT_TOPN,
                        include_timeline: bool = True) -> list[dict]:
    """Return provider dicts with hcpcs (and optionally timeline) for top-N riskiest NPIs.

    Ranks the slim cache by (risk_score desc, total_paid desc) and pulls the
    per-HCPCS aggregation from Parquet for the chosen NPIs. Each returned dict
    starts from the slim row, with `hcpcs` (and `timeline`) lists added.
    """
    from data.duckdb_client import get_connection, get_parquet_path

    slim = get_prescanned()
    if not slim:
        return []
    ranked = sorted(
        slim,
        key=lambda p: ((p.get("risk_score") or 0), (p.get("total_paid") or 0)),
        reverse=True,
    )[:top_n]
    by_npi: dict[str, dict] = {p["npi"]: dict(p) for p in ranked if p.get("npi")}
    if not by_npi:
        return []

    npi_list = list(by_npi.keys())
    placeholders = ", ".join("?" for _ in npi_list)
    params = tuple(npi_list)
    parquet = get_parquet_path()
    con = get_connection()

    t0 = time.time()

    hcpcs_sql = f"""
    SELECT
        BILLING_PROVIDER_NPI_NUM        AS npi,
        HCPCS_CODE                      AS hcpcs_code,
        SUM(TOTAL_PAID)                 AS total_paid,
        SUM(TOTAL_CLAIMS)               AS total_claims
    FROM read_parquet('{parquet}')
    WHERE BILLING_PROVIDER_NPI_NUM IN ({placeholders})
    GROUP BY npi, hcpcs_code
    ORDER BY npi, total_paid DESC
    """
    rel = con.execute(hcpcs_sql, params)
    cols = [d[0] for d in rel.description]
    for row in rel.fetchall():
        r = dict(zip(cols, row))
        by_npi[r["npi"]].setdefault("hcpcs", []).append({
            "hcpcs_code": r["hcpcs_code"],
            "total_paid": r["total_paid"] or 0,
            "total_claims": r["total_claims"] or 0,
        })

    if include_timeline:
        timeline_sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM            AS npi,
            CLAIM_FROM_MONTH                    AS month,
            SUM(TOTAL_PAID)                     AS total_paid,
            SUM(TOTAL_CLAIMS)                   AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS total_unique_beneficiaries
        FROM read_parquet('{parquet}')
        WHERE BILLING_PROVIDER_NPI_NUM IN ({placeholders})
        GROUP BY npi, month
        ORDER BY npi, month ASC
        """
        rel = con.execute(timeline_sql, params)
        cols = [d[0] for d in rel.description]
        for row in rel.fetchall():
            r = dict(zip(cols, row))
            by_npi[r["npi"]].setdefault("timeline", []).append({
                "month": r["month"],
                "total_paid": r["total_paid"] or 0,
                "total_claims": r["total_claims"] or 0,
                "total_unique_beneficiaries": r["total_unique_beneficiaries"] or 0,
            })

    logger.info(
        "[slim_cache_enricher] Enriched %d providers in %.2fs (timeline=%s)",
        len(by_npi), time.time() - t0, include_timeline,
    )
    return list(by_npi.values())
