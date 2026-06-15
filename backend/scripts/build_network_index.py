"""
Build backend/network_index.parquet — a per-NPI ego-network index that makes
/api/network/{npi} return in milliseconds instead of a full ~16s parquet scan.

Why: the dataset parquet is NOT sorted by NPI, so every network query pays a
full scan to find the rows touching one provider (a tiny provider costs as much
as a $260M mega-biller). This index pre-aggregates each provider's top-N
billing<->servicing neighbors into rows keyed by `center_npi` and SORTED by it,
so DuckDB prunes row groups and a lookup is `WHERE center_npi = '...'` — fast.

Schema (column names chosen so routes/network.py reads them directly):
    center_npi    VARCHAR   the ego provider this row belongs to
    neighbor_npi  VARCHAR   the other end of the edge (or the center itself)
    edge_type     VARCHAR   'billing_to_servicing' | 'servicing_from_billing'
                            | '__center__'  (the self aggregate)
    edge_weight   DOUBLE    SUM(TOTAL_PAID) for that edge / self total
    claim_count   BIGINT    line-item count per edge; SUM(TOTAL_CLAIMS) for self

Both directed perspectives are emitted for every (biller, servicer) pair, so a
pure-servicing provider is still found under its own center_npi. Each
(center_npi, edge_type) is capped at TOP_N — matching the route's old behavior.

Run with an interpreter that has duckdb and against the LOCAL dataset parquet
(on Dave's box that's the WindowsApps store python, which carries duckdb 1.1.1):
    "C:/Users/daveq/AppData/Local/Microsoft/WindowsApps/python.exe" \
        backend/scripts/build_network_index.py
Then upload to GCS (or let the next deploy pick it up):
    gcloud storage cp backend/network_index.parquet gs://medicaid-inspector-data/
"""
import functools
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
_INDEX_OUT = _BACKEND / "network_index.parquet"
_DATASET = _BACKEND / "data" / "medicaid-provider-spending.parquet"

# Keep the top-N strongest relationships per direction per provider. Mirrors
# TOP_N in routes/network.py — the frontend caps the rendered graph anyway.
TOP_N = 50


def build_network_index(dataset: pathlib.Path = _DATASET,
                        out_path: pathlib.Path = _INDEX_OUT) -> int:
    """Build the code-... er, NPI-sorted ego-network index. Returns row count.

    Reads the local dataset parquet once, aggregates every (biller, servicer)
    pair, emits both directed perspectives capped at TOP_N each, appends the
    per-biller self aggregate, and writes a single NPI-sorted parquet.
    """
    import duckdb

    if not (dataset.exists() and dataset.stat().st_size > 1_000_000):
        raise SystemExit(
            f"ERROR: local dataset parquet not found at {dataset}. "
            "The network index must be built from the local dataset — "
            "download it first (gcs_sync.download_parquet) or point at it."
        )

    src = str(dataset).replace("\\", "/")
    out = str(out_path).replace("\\", "/")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute(f"""
        COPY (
            WITH edges AS (
                -- one row per (biller, servicer) pair: paid + line-item count
                SELECT
                    BILLING_PROVIDER_NPI_NUM   AS b,
                    SERVICING_PROVIDER_NPI_NUM AS s,
                    SUM(TOTAL_PAID)            AS paid,
                    COUNT(*)                   AS claims
                FROM read_parquet('{src}')
                WHERE BILLING_PROVIDER_NPI_NUM   IS NOT NULL
                  AND SERVICING_PROVIDER_NPI_NUM IS NOT NULL
                  AND BILLING_PROVIDER_NPI_NUM != SERVICING_PROVIDER_NPI_NUM
                GROUP BY 1, 2
            ),
            directed AS (
                -- billing perspective: the biller is the ego, servicer the neighbor
                SELECT b AS center_npi, s AS neighbor_npi,
                       'billing_to_servicing' AS edge_type,
                       paid AS edge_weight, claims AS claim_count
                FROM edges
                UNION ALL
                -- servicing perspective: the servicer is the ego, biller the neighbor
                SELECT s AS center_npi, b AS neighbor_npi,
                       'servicing_from_billing' AS edge_type,
                       paid AS edge_weight, claims AS claim_count
                FROM edges
            ),
            top_edges AS (
                SELECT center_npi, neighbor_npi, edge_type, edge_weight, claim_count
                FROM (
                    SELECT *,
                        row_number() OVER (
                            PARTITION BY center_npi, edge_type
                            ORDER BY edge_weight DESC
                        ) AS rn
                    FROM directed
                )
                WHERE rn <= {TOP_N}
            ),
            center AS (
                -- self aggregate: total billed by this provider (billing side)
                SELECT
                    BILLING_PROVIDER_NPI_NUM AS center_npi,
                    BILLING_PROVIDER_NPI_NUM AS neighbor_npi,
                    '__center__'             AS edge_type,
                    SUM(TOTAL_PAID)          AS edge_weight,
                    SUM(TOTAL_CLAIMS)        AS claim_count
                FROM read_parquet('{src}')
                WHERE BILLING_PROVIDER_NPI_NUM IS NOT NULL
                GROUP BY 1
            )
            SELECT center_npi, neighbor_npi, edge_type, edge_weight, claim_count
            FROM top_edges
            UNION ALL
            SELECT center_npi, neighbor_npi, edge_type, edge_weight, claim_count
            FROM center
            ORDER BY center_npi
        ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]
    con.close()
    return n


def main() -> int:
    print(f"Building network index from {_DATASET.name} …")
    t = time.time()
    n = build_network_index()
    size_mb = _INDEX_OUT.stat().st_size / (1024 * 1024)
    print(f"  {n:,} rows -> {_INDEX_OUT.name} ({size_mb:.1f} MB) in {time.time() - t:.0f}s")
    print("Next: upload to GCS ->")
    print("  gcloud storage cp backend/network_index.parquet gs://medicaid-inspector-data/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
