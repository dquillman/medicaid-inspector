import re
from fastapi import APIRouter, HTTPException, Depends
from data.duckdb_client import query_async, PARQUET
from routes.auth import require_user

router = APIRouter(prefix="/api/network", tags=["network"], dependencies=[Depends(require_user)])

_NPI_RE = re.compile(r"^\d{10}$")


@router.get("/{npi}")
async def get_network(npi: str):
    """
    Ego network for a given NPI.
    Finds all NPIs that appear as SERVICING_PROVIDER_NPI_NUM when this NPI is the BILLING provider,
    and all BILLING_PROVIDER_NPI_NUM when this NPI is the SERVICING provider.
    Returns Cytoscape-ready nodes + edges.
    """
    # Validate NPI format before interpolating into SQL (prevent SQL injection)
    if not _NPI_RE.match(npi):
        raise HTTPException(400, "Invalid NPI — must be exactly 10 digits")

    # Providers this NPI billed for (as billing provider, they serviced others)
    billed_for_sql = f"""
    SELECT DISTINCT
        SERVICING_PROVIDER_NPI_NUM              AS neighbor_npi,
        SUM(TOTAL_PAID)                         AS edge_weight,
        COUNT(*)                                AS claim_count,
        'billing_to_servicing'                  AS edge_type
    FROM read_parquet('{PARQUET}')
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
      AND SERVICING_PROVIDER_NPI_NUM IS NOT NULL
      AND SERVICING_PROVIDER_NPI_NUM != '{npi}'
    GROUP BY SERVICING_PROVIDER_NPI_NUM
    ORDER BY edge_weight DESC
    LIMIT 50
    """

    # Providers that billed this NPI as servicing provider
    billed_by_sql = f"""
    SELECT DISTINCT
        BILLING_PROVIDER_NPI_NUM               AS neighbor_npi,
        SUM(TOTAL_PAID)                        AS edge_weight,
        COUNT(*)                               AS claim_count,
        'servicing_from_billing'               AS edge_type
    FROM read_parquet('{PARQUET}')
    WHERE SERVICING_PROVIDER_NPI_NUM = '{npi}'
      AND BILLING_PROVIDER_NPI_NUM IS NOT NULL
      AND BILLING_PROVIDER_NPI_NUM != '{npi}'
    GROUP BY BILLING_PROVIDER_NPI_NUM
    ORDER BY edge_weight DESC
    LIMIT 50
    """

    # Self aggregate for center node
    self_sql = f"""
    SELECT
        SUM(TOTAL_PAID)     AS total_paid,
        SUM(TOTAL_CLAIMS)   AS total_claims
    FROM read_parquet('{PARQUET}')
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    """

    import asyncio
    billed_for, billed_by, self_rows = await asyncio.gather(
        query_async(billed_for_sql),
        query_async(billed_by_sql),
        query_async(self_sql),
    )

    self_data = self_rows[0] if self_rows else {"total_paid": 0, "total_claims": 0}
    all_edges = billed_for + billed_by

    if not all_edges and not self_data["total_paid"]:
        raise HTTPException(404, f"NPI {npi} not found in dataset")

    # Build node set
    neighbor_npis = list({e["neighbor_npi"] for e in all_edges})

    # Aggregate neighbor stats
    nodes = [{"id": npi, "total_paid": self_data["total_paid"], "is_center": True}]
    for e in all_edges:
        n = e["neighbor_npi"]
        if not any(node["id"] == n for node in nodes):
            nodes.append({"id": n, "total_paid": 0, "is_center": False})

    edges = [
        {
            "source": npi if e["edge_type"] == "billing_to_servicing" else e["neighbor_npi"],
            "target": e["neighbor_npi"] if e["edge_type"] == "billing_to_servicing" else npi,
            "weight": e["edge_weight"],
            "claim_count": e["claim_count"],
            "type": e["edge_type"],
        }
        for e in all_edges
    ]

    return {"center_npi": npi, "nodes": nodes, "edges": edges}
