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


def _ensure_reference_data() -> None:
    """Guarantee the per-se-fraud lookups are populated BEFORE scoring.

    dead_npi_billing and oig_excluded are the highest-value signals — but they
    silently score 0 for EVERY provider if their lookup files are missing
    (the stores load to an empty dict). Pull npi_deactivations.json from GCS if
    it isn't local, then report the loaded counts so a dark signal is obvious.
    """
    import os
    dpath = _BACKEND / "npi_deactivations.json"
    if not dpath.exists():
        try:
            from google.cloud import storage
            bucket = storage.Client().bucket(os.environ.get("GCS_BUCKET", "medicaid-inspector-data"))
            blob = bucket.get_blob("npi_deactivations.json")
            if blob:
                blob.download_to_filename(str(dpath))
                print("  pulled npi_deactivations.json from GCS")
        except Exception as e:  # noqa: BLE001
            print(f"  WARN: npi_deactivations.json missing and GCS fetch failed ({e}) — dead_npi_billing will be DARK")
    try:
        from core.deactivation_store import count as _deact_count
        from core.oig_store import load_oig_from_disk, get_oig_stats
        # The OIG store has NO lazy-load (unlike deactivation_store) — it must be
        # loaded explicitly, which the server does at startup but the bulk
        # rebuild never did, so oig_excluded silently scored 0 for everyone.
        load_oig_from_disk()
        oig = int((get_oig_stats() or {}).get("record_count") or 0)
        dc = _deact_count()
        dark = [n for n, c in (("dead_npi_billing", dc), ("oig_excluded", oig)) if c == 0]
        print(f"Per-se-fraud reference loaded: {dc} deactivated NPIs, {oig} OIG exclusions"
              + (f"  WARN: {' + '.join(dark)} will be DARK" if dark else "  (both armed)"))
    except Exception as e:  # noqa: BLE001
        print(f"  WARN: could not verify per-se-fraud reference data ({e})")


async def main():
    import duckdb
    from data.duckdb_client import get_parquet_path
    from services.scan_engine import _import_signals, _score_provider, _build_peer_stats
    from collections import defaultdict
    from core.config import settings

    _ensure_reference_data()
    sig = _import_signals()
    parquet = get_parquet_path()
    print(f"Parquet: {parquet}")

    print(f"Reading NPI list from {_SLIM.name}…")
    with open(_SLIM, encoding="utf-8") as f:
        slim = json.load(f)
    slim_provs = slim.get("providers", [])
    npis = [p["npi"] for p in slim_provs if p.get("npi")]
    scan_progress = slim.get("scan_progress", {})
    print(f"  {len(npis):,} NPIs")

    # Fold in the missing-provider top-up (missing_npis.json — the dollar-rank
    # gap plus per-se leads below the old cutoff). The in-app button cannot do
    # this reliably: it runs as a background task on Cloud Run, a background
    # task is not traffic, so the instance gets reclaimed on a long idle scan
    # and the whole run is lost (observed twice, 2026-07-26 and overnight
    # 2026-07-27). Locally it is one extra INNER JOIN on an already-running
    # scan, and it persists because the workstation is not going anywhere.
    _missing_path = _BACKEND / "missing_npis.json"
    if _missing_path.exists():
        try:
            _m = json.loads(_missing_path.read_text(encoding="utf-8"))
            _have = set(npis)
            _add = [n for n in _m.get("npis", []) if n not in _have]
            if _add:
                npis.extend(_add)
                print(f"  + {len(_add):,} missing providers "
                      f"({len(_m.get('rank_gap', [])):,} rank-gap, "
                      f"{len(_m.get('perse', [])):,} per-se) -> {len(npis):,} total")
        except (OSError, ValueError) as e:
            print(f"  WARN: missing_npis.json unreadable ({e}) — scanning the cache list only")
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

    # The MUP pre-load that used to sit here is gone: it existed solely to feed
    # diagnosis_procedure_mismatch, retired 2026-07-26 (it fired on 2 of 106,660
    # and was the only signal reading Medicare data to judge Medicaid claims).
    # No scored signal reads MUP any more.

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

    # ── Cluster sizes, computed from the SLIM cache's NPPES enrichment ───────
    # compute_address_clusters()/compute_auth_official_clusters() read
    # core.store.get_prescanned(), which is empty on a workstation that has no
    # populated prescan_cache.json — so they would silently return {} and every
    # provider would score 0 on both cluster signals. That is precisely how
    # address_cluster_risk and corporate_shell_risk came to be dark. Build them
    # from the slim enrichment we already loaded instead.
    def _clusters(path_fn) -> dict:
        groups: dict[str, list[str]] = {}
        key: dict[str, str] = {}
        for sp in slim_provs:
            k = path_fn(sp)
            if not k:
                continue
            groups.setdefault(k, []).append(sp["npi"])
            key[sp["npi"]] = k
        return {n: len(groups[k]) for n, k in key.items()}

    def _addr_key(sp: dict) -> str:
        a = (sp.get("nppes") or {}).get("address") or {}
        z = (a.get("zip") or "")[:5].strip()
        s = (a.get("line1") or "").strip().upper()
        return f"{z}|{s}" if z and s else ""

    def _ao_key(sp: dict) -> str:
        ao = (sp.get("nppes") or {}).get("authorized_official") or {}
        return (ao.get("name") or "").strip().upper()

    cluster_sizes = _clusters(_addr_key)
    auth_clusters = _clusters(_ao_key)
    print(f"  address clusters: {len(cluster_sizes):,} providers placed, "
          f"{sum(1 for v in cluster_sizes.values() if v >= 3):,} in a cluster of 3+")
    print(f"  official clusters: {len(auth_clusters):,} providers placed, "
          f"{sum(1 for v in auth_clusters.values() if v >= 3):,} in a cluster of 3+")

    # NPPES/identity enrichment, keyed by NPI. Five signals READ these fields —
    # specialty_mismatch (specialty/taxonomy), new_provider_explosion
    # (nppes.enumeration_date), geographic_impossibility (state) and both cluster
    # signals. The row used to be `{**agg}` — DuckDB aggregates only — so those
    # fields were absent at scoring time and every one of those signals returned
    # "no data available" for all 106,660 providers. Enrichment lands in the
    # cache AFTER scoring, which is why they were dark from day one rather than
    # by any single bug. Merge it in BEFORE scoring, and carry it through to the
    # output so a rebuild no longer discards identity data.
    _ENRICH_KEYS = ("nppes", "specialty", "state", "city", "zip", "provider_name")
    enrich = {
        sp["npi"]: {k: sp[k] for k in _ENRICH_KEYS if sp.get(k) is not None}
        for sp in slim_provs if sp.get("npi")
    }
    _with_spec = sum(1 for e in enrich.values() if e.get("specialty"))
    _with_enum = sum(1 for e in enrich.values() if (e.get("nppes") or {}).get("enumeration_date"))
    print(f"  enrichment available: {_with_spec:,} with specialty, {_with_enum:,} with enumeration date")

    scored: list[dict] = []
    for i, (npi, agg) in enumerate(agg_by_npi.items()):
        hl = hcpcs_by_npi.get(npi, [])
        tl = timeline_by_npi.get(npi, [])
        top = hl[0]["hcpcs_code"] if hl else ""
        row = {**agg, "top_hcpcs": top, **enrich.get(npi, {})}
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
    print(f"DONE: {len(scored):,} providers rebuilt")
    print(f"  high-risk (score>=50): {flagged:,}")
    print()

    # Per-signal fire rate. A signal at 0.0% here is DARK — its inputs were
    # missing at scoring time. That is exactly how five signals went unnoticed
    # for months (audit 2026-07-26), so the rebuild now reports it every run
    # instead of leaving it to be discovered.
    from collections import Counter as _C
    fired, evaluated = _C(), _C()
    for p in scored:
        for s in p.get("signal_results", []):
            evaluated[s["signal"]] += 1
            if s.get("flagged"):
                fired[s["signal"]] += 1
    n = len(scored) or 1
    print("  signal fire rates:")
    for name in sorted(evaluated, key=lambda k: -fired[k]):
        pct = 100 * fired[name] / n
        mark = "   <-- DARK" if fired[name] == 0 else ""
        print(f"    {fired[name]:7,}  ({pct:5.2f}%)  {name}{mark}")


if __name__ == "__main__":
    asyncio.run(main())
