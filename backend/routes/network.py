import asyncio
import pathlib
import re
from fastapi import APIRouter, HTTPException, Depends
from data.duckdb_client import query_async, get_parquet_path
from routes.auth import require_user

router = APIRouter(prefix="/api/network", tags=["network"], dependencies=[Depends(require_user)])

_NPI_RE = re.compile(r"^\d{10}$")

# Workstation-precomputed ego-network index, sorted by center_npi so a per-NPI
# lookup is a row-group-pruned `WHERE center_npi = '...'` (milliseconds) instead
# of a full ~16s scan of the unsorted 2.74 GB dataset. Built by
# scripts/build_network_index.py and synced from GCS at startup. When absent
# (e.g. fresh local dev), we fall back to the live materialized full-scan below.
_NETWORK_INDEX = pathlib.Path(__file__).parent.parent / "network_index.parquet"


def _index_available() -> bool:
    return _NETWORK_INDEX.exists() and _NETWORK_INDEX.stat().st_size > 1_000

# Keep the top-N strongest relationships per direction. The frontend caps the
# rendered graph at 140 nodes; 50 each way (+ center) stays comfortably under it.
TOP_N = 50

# Wall-clock guard. A handful of mega-providers (e.g. $260M billers) touch so
# many rows that the aggregation scan runs long. Rather than hang the UI, bail
# out with a clean error. Because run_query() caches by SQL string, a query
# that eventually finishes in the background populates the cache, so a retry
# typically returns instantly.
QUERY_TIMEOUT_SECONDS = 45


@router.get("/{npi}")
async def get_network(npi: str):
    """
    Ego network for a given NPI.
    Finds all NPIs that appear as SERVICING_PROVIDER_NPI_NUM when this NPI is the
    BILLING provider, and all BILLING_PROVIDER_NPI_NUM when this NPI is the
    SERVICING provider. Returns Cytoscape-ready nodes + edges.

    Single materialized scan: the parquet is read once, filtered to only the
    rows that touch this NPI, then both edge directions and the center
    aggregate are derived from that in-memory slice — instead of three separate
    full scans of the remote file.
    """
    # Validate NPI format before interpolating into SQL (prevent SQL injection)
    if not _NPI_RE.match(npi):
        raise HTTPException(400, "Invalid NPI — must be exactly 10 digits")

    if _index_available():
        # Fast path: read the pre-aggregated, NPI-sorted index. DuckDB prunes to
        # the row group(s) for this center_npi, so this returns in milliseconds.
        idx = str(_NETWORK_INDEX).replace("\\", "/")
        sql = f"""
        SELECT neighbor_npi, edge_type, edge_weight, claim_count
        FROM read_parquet('{idx}')
        WHERE center_npi = '{npi}'
        """
    else:
        # Fallback: live single-scan materialization (slow but correct) for envs
        # where the precomputed index hasn't been synced yet.
        src = f"read_parquet('{get_parquet_path()}')"

        # One scan: `base` is MATERIALIZED so DuckDB evaluates it exactly once, with
        # the NPI filter pushed down to the parquet row groups. `edges` ranks each
        # direction and keeps the top-N; `center` is the self aggregate.
        sql = f"""
        WITH base AS MATERIALIZED (
            SELECT
                BILLING_PROVIDER_NPI_NUM   AS b,
                SERVICING_PROVIDER_NPI_NUM AS s,
                TOTAL_PAID                 AS paid,
                TOTAL_CLAIMS               AS claims
            FROM {src}
            WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
               OR SERVICING_PROVIDER_NPI_NUM = '{npi}'
        ),
        edges_agg AS (
            SELECT
                CASE WHEN b = '{npi}' THEN s ELSE b END                          AS neighbor_npi,
                CASE WHEN b = '{npi}' THEN 'billing_to_servicing'
                     ELSE 'servicing_from_billing' END                          AS edge_type,
                SUM(paid)  AS edge_weight,
                COUNT(*)   AS claim_count
            FROM base
            WHERE (b = '{npi}' AND s IS NOT NULL AND s != '{npi}')
               OR (s = '{npi}' AND b IS NOT NULL AND b != '{npi}')
            GROUP BY 1, 2
        ),
        edges AS (
            SELECT neighbor_npi, edge_type, edge_weight, claim_count
            FROM (
                SELECT *,
                    row_number() OVER (PARTITION BY edge_type ORDER BY edge_weight DESC) AS rn
                FROM edges_agg
            )
            WHERE rn <= {TOP_N}
        ),
        center AS (
            SELECT
                '{npi}'        AS neighbor_npi,
                '__center__'   AS edge_type,
                SUM(paid)      AS edge_weight,
                SUM(claims)    AS claim_count
            FROM base
            WHERE b = '{npi}'
        )
        SELECT neighbor_npi, edge_type, edge_weight, claim_count FROM edges
        UNION ALL
        SELECT neighbor_npi, edge_type, edge_weight, claim_count FROM center
        """

    try:
        rows = await asyncio.wait_for(query_async(sql), timeout=QUERY_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(
            504,
            f"NPI {npi} has too large a network to compute within "
            f"{QUERY_TIMEOUT_SECONDS}s. The result is still being cached in the "
            f"background — try again in a moment.",
        )

    center_row = next((r for r in rows if r["edge_type"] == "__center__"), None)
    edge_rows = [r for r in rows if r["edge_type"] != "__center__"]

    self_paid = (center_row["edge_weight"] if center_row else 0) or 0
    self_claims = (center_row["claim_count"] if center_row else 0) or 0

    if not edge_rows and not self_paid:
        raise HTTPException(404, f"NPI {npi} not found in dataset")

    # Build node set — center first, then unique neighbors
    nodes = [{"id": npi, "total_paid": self_paid, "total_claims": self_claims, "is_center": True}]
    seen = {npi}
    for e in edge_rows:
        n = e["neighbor_npi"]
        if n not in seen:
            seen.add(n)
            nodes.append({"id": n, "total_paid": 0, "is_center": False})

    edges = [
        {
            "source": npi if e["edge_type"] == "billing_to_servicing" else e["neighbor_npi"],
            "target": e["neighbor_npi"] if e["edge_type"] == "billing_to_servicing" else npi,
            "weight": e["edge_weight"],
            "claim_count": e["claim_count"],
            "type": e["edge_type"],
        }
        for e in edge_rows
    ]

    return {"center_npi": npi, "nodes": nodes, "edges": edges}
