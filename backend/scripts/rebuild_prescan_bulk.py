"""
Bulk rebuild — does 3 unfiltered parquet scans (no WHERE IN) and JOINs
against the target NPI list in DuckDB. Avoids the per-batch full-scan
overhead of rebuild_prescan_cache.py.

Total runtime target: ~5-15 min for 106k providers.

Usage: python backend/scripts/rebuild_prescan_bulk.py
"""
import asyncio
import json
import logging
import pathlib
import sys
import time
import functools

# Force line buffering so progress shows up immediately when piped to a file.
print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")

_SLIM = _BACKEND / "prescan_slim.json"
_FULL = _BACKEND / "prescan_cache.json"
_TMP = _BACKEND / "prescan_cache.json.rebuilding"


async def main():
    import duckdb
    from data.duckdb_client import get_parquet_path
    from services.scan_engine import _import_signals, _score_provider, _build_peer_stats
    from collections import defaultdict
    from core.config import settings

    sig = _import_signals()
    parquet = get_parquet_path()
    print(f"Parquet: {parquet}")

    print(f"Reading NPI list from {_SLIM.name}…")
    with open(_SLIM, encoding="utf-8") as f:
        slim = json.load(f)
    npis = [p["npi"] for p in slim.get("providers", []) if p.get("npi")]
    scan_progress = slim.get("scan_progress", {})
    print(f"  {len(npis):,} NPIs")
    print()

    # One DuckDB connection used for all three big queries — keeping the
    # NPI list in a temp table avoids stringifying 106k literals into SQL.
    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    con.execute("SET threads=4;")

    # Insert via CSV — executemany was hanging at ~106k rows (each row was
    # its own implicit transaction). COPY FROM read_csv is ~1000x faster.
    npi_csv = _BACKEND / "_npi_targets.csv.tmp"
    print(f"  writing NPI list to {npi_csv.name} for bulk insert…")
    t0 = time.time()
    with open(npi_csv, "w", encoding="utf-8") as f:
        f.write("npi\n")
        for n in npis:
            f.write(f"{n}\n")
    npi_path = str(npi_csv).replace("\\", "/")
    con.execute(f"""
        CREATE TEMP TABLE target_npis AS
        SELECT npi FROM read_csv_auto('{npi_path}', header=true)
    """)
    n_target = con.execute("SELECT COUNT(*) FROM target_npis").fetchone()[0]
    print(f"  loaded {n_target:,} target NPIs into DuckDB temp table in {time.time() - t0:.1f}s")
    try:
        npi_csv.unlink()
    except OSError:
        pass
    print()

    # ── Aggregate query (1 scan) ─────────────────────────────────────────────
    print("Query 1/3: provider aggregates…")
    t0 = time.time()
    agg_rows = con.execute(f"""
        SELECT
            p.BILLING_PROVIDER_NPI_NUM    AS npi,
            SUM(p.TOTAL_PAID)             AS total_paid,
            SUM(p.TOTAL_CLAIMS)           AS total_claims,
            SUM(p.TOTAL_UNIQUE_BENEFICIARIES) AS total_beneficiaries,
            COUNT(DISTINCT p.HCPCS_CODE)  AS distinct_hcpcs,
            COUNT(DISTINCT p.CLAIM_FROM_MONTH) AS active_months,
            MIN(p.CLAIM_FROM_MONTH)       AS first_month,
            MAX(p.CLAIM_FROM_MONTH)       AS last_month,
            CAST(SUM(p.TOTAL_PAID) AS DOUBLE) / NULLIF(SUM(p.TOTAL_UNIQUE_BENEFICIARIES), 0) AS revenue_per_beneficiary,
            CAST(SUM(p.TOTAL_CLAIMS) AS DOUBLE) / NULLIF(SUM(p.TOTAL_UNIQUE_BENEFICIARIES), 0) AS claims_per_beneficiary
        FROM read_parquet('{parquet}') p
        INNER JOIN target_npis t ON p.BILLING_PROVIDER_NPI_NUM = t.npi
        GROUP BY p.BILLING_PROVIDER_NPI_NUM
    """).fetchall()
    cols = [d[0] for d in con.description]
    agg_by_npi = {row[cols.index("npi")]: dict(zip(cols, row)) for row in agg_rows}
    print(f"  {len(agg_by_npi):,} provider aggregates in {time.time() - t0:.1f}s")
    print()

    # ── HCPCS breakdown (1 scan) ─────────────────────────────────────────────
    print("Query 2/3: HCPCS breakdown…")
    t0 = time.time()
    hcpcs_rows = con.execute(f"""
        SELECT
            p.BILLING_PROVIDER_NPI_NUM    AS npi,
            p.HCPCS_CODE                  AS hcpcs_code,
            SUM(p.TOTAL_PAID)             AS total_paid,
            SUM(p.TOTAL_CLAIMS)           AS total_claims
        FROM read_parquet('{parquet}') p
        INNER JOIN target_npis t ON p.BILLING_PROVIDER_NPI_NUM = t.npi
        GROUP BY p.BILLING_PROVIDER_NPI_NUM, p.HCPCS_CODE
        ORDER BY p.BILLING_PROVIDER_NPI_NUM, total_paid DESC
    """).fetchall()
    hcols = [d[0] for d in con.description]
    hcpcs_by_npi: dict = defaultdict(list)
    for row in hcpcs_rows:
        d = dict(zip(hcols, row))
        hcpcs_by_npi[d["npi"]].append(d)
    print(f"  {len(hcpcs_rows):,} HCPCS rows in {time.time() - t0:.1f}s")
    print()

    # ── Timeline (1 scan) ────────────────────────────────────────────────────
    print("Query 3/3: monthly timelines…")
    t0 = time.time()
    timeline_rows = con.execute(f"""
        SELECT
            p.BILLING_PROVIDER_NPI_NUM        AS npi,
            p.CLAIM_FROM_MONTH                AS month,
            SUM(p.TOTAL_PAID)                 AS total_paid,
            SUM(p.TOTAL_CLAIMS)               AS total_claims,
            SUM(p.TOTAL_UNIQUE_BENEFICIARIES) AS total_unique_beneficiaries
        FROM read_parquet('{parquet}') p
        INNER JOIN target_npis t ON p.BILLING_PROVIDER_NPI_NUM = t.npi
        GROUP BY p.BILLING_PROVIDER_NPI_NUM, p.CLAIM_FROM_MONTH
        ORDER BY p.BILLING_PROVIDER_NPI_NUM, p.CLAIM_FROM_MONTH
    """).fetchall()
    tcols = [d[0] for d in con.description]
    timeline_by_npi: dict = defaultdict(list)
    for row in timeline_rows:
        d = dict(zip(tcols, row))
        timeline_by_npi[d["npi"]].append(d)
    print(f"  {len(timeline_rows):,} timeline rows in {time.time() - t0:.1f}s")
    print()

    # ── Pre-load MUP rows for all target NPIs into a dict (one bulk query
    # instead of 106k individual lookups during scoring). ──
    print("Pre-loading MUP diagnosis data for all targets…")
    t0 = time.time()
    try:
        from services import mup_cache
        if mup_cache.is_local():
            mup_path = str(mup_cache.get_local_path()).replace("\\", "/")
            mup_rows = con.execute(f"""
                SELECT m.*
                FROM read_parquet('{mup_path}') m
                INNER JOIN target_npis t ON m.Rndrng_NPI = t.npi
            """).fetchall()
            mup_cols = [d[0] for d in con.description]
            mup_by_npi: dict = {}
            npi_idx = mup_cols.index("Rndrng_NPI")
            for row in mup_rows:
                mup_by_npi[row[npi_idx]] = dict(zip(mup_cols, row))
            print(f"  pre-loaded {len(mup_by_npi):,} MUP rows in {time.time() - t0:.1f}s")
        else:
            mup_by_npi = {}
            print("  MUP cache not present — skipping")
    except Exception as e:
        print(f"  MUP pre-load failed (non-fatal, will fall back per-NPI): {e}")
        mup_by_npi = {}
    print()

    # ── Score everything ─────────────────────────────────────────────────────
    print("Scoring all providers…")
    t0 = time.time()

    # Peer stats from the aggregates we just pulled
    peer_rpb: dict = defaultdict(list)
    peer_cpb: dict = defaultdict(list)
    all_spend: list[float] = []
    for npi, agg in agg_by_npi.items():
        hl = hcpcs_by_npi.get(npi, [])
        top = hl[0]["hcpcs_code"] if hl else ""
        rpb = agg.get("revenue_per_beneficiary") or 0
        cpb = agg.get("claims_per_beneficiary") or 0
        sp = agg.get("total_paid") or 0
        if top and rpb > 0:
            peer_rpb[top].append(float(rpb))
        if top and cpb > 0:
            peer_cpb[top].append(float(cpb))
        if sp > 0:
            all_spend.append(float(sp))

    peer_stats, cpb_stats, spend_mean, spend_std = _build_peer_stats(
        list(agg_by_npi.values()), peer_rpb, peer_cpb, all_spend
    )
    cluster_sizes = sig["compute_address_clusters"]()
    auth_clusters = sig["compute_auth_official_clusters"]()

    # Monkey-patch mup_lookup_sync so the scoring loop uses our pre-loaded
    # dict instead of hitting DuckDB once per provider (which was the bottleneck).
    from services import mup_client
    original_lookup = mup_client.lookup_sync
    mup_client.lookup_sync = lambda npi: mup_by_npi.get(npi)
    sig["mup_lookup_sync"] = mup_client.lookup_sync

    scored: list[dict] = []
    for i, (npi, agg) in enumerate(agg_by_npi.items()):
        hl = hcpcs_by_npi.get(npi, [])
        tl = timeline_by_npi.get(npi, [])
        top = hl[0]["hcpcs_code"] if hl else ""
        row = {**agg, "top_hcpcs": top}
        scored.append(_score_provider(
            row, hl, tl, npi, top,
            peer_stats, cpb_stats, spend_mean, spend_std,
            cluster_sizes, auth_clusters, sig,
        ))
        if (i + 1) % 10000 == 0:
            rate = (i + 1) / (time.time() - t0)
            eta = (len(agg_by_npi) - i - 1) / rate
            print(f"  scored {i+1:,}/{len(agg_by_npi):,}  ({rate:.0f}/s, ETA {eta:.0f}s)")
    print(f"  scored {len(scored):,} providers in {time.time() - t0:.1f}s")
    mup_client.lookup_sync = original_lookup  # restore
    print()

    # ── Write final cache ────────────────────────────────────────────────────
    print("Writing prescan_cache.json…")
    t0 = time.time()
    out = {
        "parquet_url": settings.PARQUET_URL,
        "saved_at": time.time(),
        "scan_progress": scan_progress,
        "providers": sorted(scored, key=lambda p: p.get("total_paid") or 0, reverse=True),
    }
    with open(_TMP, "w", encoding="utf-8") as f:
        json.dump(out, f, default=str)
    _TMP.replace(_FULL)
    print(f"  wrote in {time.time() - t0:.1f}s")
    print(f"  size: {_FULL.stat().st_size / 1_048_576:.1f} MB")
    print()

    flagged = sum(1 for p in scored if p.get("risk_score", 0) >= 50)
    with_new = sum(
        1 for p in scored
        if any(s.get("signal") == "diagnosis_procedure_mismatch" for s in p.get("signal_results", []))
    )
    new_flagged = sum(
        1 for p in scored
        if any(s.get("signal") == "diagnosis_procedure_mismatch" and s.get("flagged")
               for s in p.get("signal_results", []))
    )
    print(f"DONE: {len(scored):,} providers rebuilt")
    print(f"  high-risk (score≥50): {flagged:,}")
    print(f"  with diagnosis_procedure_mismatch evaluated: {with_new:,}")
    print(f"  flagged by diagnosis_procedure_mismatch: {new_flagged:,}")


if __name__ == "__main__":
    asyncio.run(main())
