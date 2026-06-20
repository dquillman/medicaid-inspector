"""
Precompute the heavy claim-level analyses from the FULL prescan cache and
write backend/precomputed_analyses.json (a few MB).

Why: Cloud Run runs on the slim cache (no per-HCPCS detail) inside a 2 GiB
container — it can neither load the 1.4 GB full cache nor query the remote
parquet within the request timeout. So the analyses run here, on a machine
with the full cache, and prod serves the stored results.

Run after every full scan / dataset refresh — use an interpreter that has the
backend deps installed (duckdb etc.); on Dave's machine that's G:\Python311:
    G:\Python311\python.exe backend/scripts/precompute_analyses.py
Then upload to GCS (or let the next deploy pick it up):
    gcloud storage cp backend/precomputed_analyses.json gs://medicaid-inspector-data/

Sections: claim_patterns, pharmacy_high_risk, dme_high_risk, doctor_shopping.
"""
import asyncio
import datetime
import functools
import json
import logging
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")

_OUT = _BACKEND / "precomputed_analyses.json"
_LIMIT = 500  # matches the max limit the API routes accept


_INDEX_OUT = _BACKEND / "hcpcs_index.parquet"


def _write_hcpcs_index(providers: list[dict]) -> None:
    """Build a code-sorted per-(npi, code) aggregate parquet.

    Column names match the big dataset parquet so routes/billing_codes.py can
    run its existing SQL against this file unchanged. Sorting by HCPCS_CODE
    gives DuckDB row-group pruning on per-code lookups.

    Preferred source is the LOCAL dataset parquet — it yields every code per
    NPI (the cache stores only the top 50) and includes beneficiary counts,
    which the cache's hcpcs arrays never had. Falls back to flattening the
    cache when the dataset isn't on disk.
    """
    import csv
    import tempfile

    import duckdb

    dataset = _BACKEND / "data" / "medicaid-provider-spending.parquet"
    if dataset.exists() and dataset.stat().st_size > 1_000_000:
        src = str(dataset).replace("\\", "/")
        out_path = str(_INDEX_OUT).replace("\\", "/")
        con = duckdb.connect()
        con.execute(f"""
            COPY (
                SELECT
                    BILLING_PROVIDER_NPI_NUM,
                    HCPCS_CODE,
                    SUM(TOTAL_PAID)                  AS TOTAL_PAID,
                    SUM(TOTAL_CLAIMS)                AS TOTAL_CLAIMS,
                    SUM(TOTAL_UNIQUE_BENEFICIARIES)  AS TOTAL_UNIQUE_BENEFICIARIES
                FROM read_parquet('{src}')
                WHERE BILLING_PROVIDER_NPI_NUM IS NOT NULL
                  AND HCPCS_CODE IS NOT NULL
                GROUP BY BILLING_PROVIDER_NPI_NUM, HCPCS_CODE
                ORDER BY HCPCS_CODE, TOTAL_PAID DESC
            ) TO '{out_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
        con.close()
        size_mb = _INDEX_OUT.stat().st_size / (1024 * 1024)
        print(f"  {n:,} rows (from local dataset, with beneficiaries) -> {_INDEX_OUT.name} ({size_mb:.1f} MB)")
        return

    # dir=_BACKEND: the default %TEMP% lives on C:, which is chronically full
    # on this machine — keep the ~150 MB scratch CSV on the same drive as the
    # repo instead.
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", suffix=".csv", delete=False, dir=str(_BACKEND),
    ) as f:
        tmp_csv = f.name
        w = csv.writer(f)
        w.writerow(["BILLING_PROVIDER_NPI_NUM", "HCPCS_CODE", "TOTAL_PAID", "TOTAL_CLAIMS"])
        n = 0
        for p in providers:
            npi = p.get("npi")
            if not npi:
                continue
            for h in (p.get("hcpcs") or []):
                code = (h.get("hcpcs_code") or "").strip().upper()
                if not code:
                    continue
                w.writerow([npi, code,
                            float(h.get("total_paid") or 0),
                            int(h.get("total_claims") or 0)])
                n += 1
    con = duckdb.connect()
    csv_path = tmp_csv.replace("\\", "/")
    out_path = str(_INDEX_OUT).replace("\\", "/")
    con.execute(f"""
        COPY (
            SELECT * FROM read_csv('{csv_path}', header=true,
                columns={{'BILLING_PROVIDER_NPI_NUM':'VARCHAR','HCPCS_CODE':'VARCHAR',
                          'TOTAL_PAID':'DOUBLE','TOTAL_CLAIMS':'BIGINT'}})
            ORDER BY HCPCS_CODE, TOTAL_PAID DESC
        ) TO '{out_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.close()
    pathlib.Path(tmp_csv).unlink(missing_ok=True)
    size_mb = _INDEX_OUT.stat().st_size / (1024 * 1024)
    print(f"  {n:,} rows -> {_INDEX_OUT.name} ({size_mb:.1f} MB)")


def rebuild_slim_scores(providers: list[dict]) -> int:
    """Refresh prescan_slim.json scoring fields from a freshly-scored full cache.

    The slim cache is what PROD serves, but a scan rebuild only rewrites the full
    cache (prescan_cache.json) — without this step prod keeps the OLD risk scores
    after a data refresh. We MERGE per NPI: overwrite the scoring + aggregate
    fields, but PRESERVE each provider's NPPES-derived name/specialty/geo, which a
    scan does not produce (those come from separate NPPES enrichment and must
    survive a refresh). New NPIs get blank geo, to be enriched later. Returns the
    number of providers written.
    """
    slim_path = _BACKEND / "prescan_slim.json"

    existing: dict[str, dict] = {}
    top: dict = {}
    if slim_path.exists():
        with open(slim_path, encoding="utf-8") as f:
            cur = json.load(f)
        top = {k: cur.get(k) for k in ("scan_progress", "prescan_status") if cur.get(k) is not None}
        for sp in cur.get("providers", []):
            if sp.get("npi"):
                existing[sp["npi"]] = sp

    score_fields = (
        "total_paid", "total_claims", "total_beneficiaries", "distinct_hcpcs",
        "active_months", "first_month", "last_month", "risk_score",
        # Needed by the signal-evidence endpoint so its proof boxes show real
        # numbers (and can cohort-match peers) on the slim-only prod deployment —
        # without these the boxes read 0 and showed "0.0".
        "claims_per_beneficiary", "revenue_per_beneficiary", "top_hcpcs",
    )

    out: list[dict] = []
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue
        prev = existing.get(npi, {})
        flags = p.get("flags") or []
        nppes = p.get("nppes") if isinstance(p.get("nppes"), dict) else {}
        addr = (nppes.get("address") or {}) if nppes else {}
        tax = (nppes.get("taxonomy") or {}) if nppes else {}
        rec: dict = {"npi": npi}
        for k in score_fields:
            rec[k] = p.get(k, prev.get(k))
        rec["flags"] = flags
        rec["flag_count"] = len(flags)
        # Prefer the full record's enrichment if present, else keep the old slim's.
        rec["provider_name"] = p.get("provider_name") or nppes.get("name") or prev.get("provider_name", "")
        rec["specialty"] = p.get("specialty") or tax.get("description") or prev.get("specialty", "")
        rec["state"] = p.get("state") or addr.get("state") or prev.get("state", "")
        rec["city"] = p.get("city") or addr.get("city") or prev.get("city", "")
        rec["zip"] = p.get("zip") or addr.get("zip") or prev.get("zip", "")
        out.append(rec)

    out.sort(key=lambda r: r.get("total_paid") or 0, reverse=True)
    slim = {"providers": out, **top}
    tmp = slim_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slim, f, separators=(",", ":"), default=str)
    tmp.replace(slim_path)
    return len(out)


def backfill_slim_fields(providers: list[dict]) -> int:
    """Fill empty top-level fields in prescan_slim.json from the full cache.

    The slim cache was generated without specialty (and with gaps in
    name/state/city/zip), which left prod's Specialty Benchmark comparing
    every provider against one giant 'Unknown' bucket. Returns count fixed.
    """
    slim_path = _BACKEND / "prescan_slim.json"
    if not slim_path.exists():
        return 0

    lookup: dict[str, dict] = {}
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue
        nppes = p.get("nppes") or {}
        addr = nppes.get("address") or {}
        lookup[npi] = {
            "specialty": (nppes.get("taxonomy") or {}).get("description") or "",
            "provider_name": nppes.get("name") or p.get("provider_name") or "",
            "state": addr.get("state") or p.get("state") or "",
            "city": addr.get("city") or p.get("city") or "",
            "zip": addr.get("zip") or p.get("zip") or "",
        }

    with open(slim_path, encoding="utf-8") as f:
        slim = json.load(f)
    fixed = 0
    for sp in slim.get("providers", []):
        src = lookup.get(sp.get("npi"))
        if not src:
            continue
        changed = False
        for k, v in src.items():
            if v and not (sp.get(k) or "").strip():
                sp[k] = v
                changed = True
        fixed += changed

    tmp = slim_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slim, f, separators=(",", ":"), default=str)
    tmp.replace(slim_path)
    return fixed


def _inject_specialty_from_slim(providers: list[dict]) -> int:
    """The full prescan cache carries no NPPES data, so detectors that run on it
    (DME, pharmacy, claim patterns) can't tell a DME supplier from a clinician.
    The slim cache DOES carry specialty (preserved across rebuilds). Copy it onto
    the in-memory provider objects so provider-type-aware detectors work during
    precompute exactly as they do on prod (where get_prescanned() == the slim)."""
    slim_path = _BACKEND / "prescan_slim.json"
    if not slim_path.exists():
        return 0
    try:
        slim = json.loads(slim_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    rows = slim if isinstance(slim, list) else slim.get("providers", [])
    spec = {str(r.get("npi")): r.get("specialty") for r in rows if r.get("specialty")}
    n = 0
    for p in providers:
        if not p.get("specialty"):
            s = spec.get(str(p.get("npi")))
            if s:
                p["specialty"] = s
                n += 1
    return n


def main() -> int:
    from core.store import load_prescanned_from_disk, get_prescanned

    print("Loading full prescan cache (this parses ~1.4 GB of JSON; takes a few minutes)…")
    t0 = time.time()
    if not load_prescanned_from_disk():
        print("ERROR: could not load prescan_cache.json — run a full scan first.")
        return 1
    providers = get_prescanned()
    print(f"Loaded {len(providers):,} providers in {time.time() - t0:.0f}s")

    n_spec = _inject_specialty_from_slim(providers)
    print(f"Injected specialty onto {n_spec:,} providers from slim "
          f"(enables provider-type-aware detectors)")

    from services.slim_cache_enricher import has_hcpcs_detail
    if not has_hcpcs_detail():
        print("ERROR: loaded cache has no per-HCPCS detail (slim cache?). "
              "Precompute needs the FULL cache.")
        return 1

    out: dict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "provider_count": len(providers),
        "limit": _LIMIT,
    }

    print("Computing claim patterns…")
    t = time.time()
    from services.claim_patterns import _compute_all_from_cache
    out["claim_patterns"] = _compute_all_from_cache(limit=_LIMIT)
    print(f"  done in {time.time() - t:.0f}s "
          f"({sum(len(v) for v in out['claim_patterns'].values() if isinstance(v, list))} findings)")

    print("Computing pharmacy high-risk…")
    t = time.time()
    from services.pharmacy_analyzer import get_high_risk_providers as pharm_high_risk
    out["pharmacy_high_risk"] = asyncio.run(pharm_high_risk(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s ({out['pharmacy_high_risk'].get('total', 0)} providers)")

    print("Computing DME high-risk…")
    t = time.time()
    from services.dme_analyzer import get_high_risk_providers as dme_high_risk
    out["dme_high_risk"] = asyncio.run(dme_high_risk(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s ({out['dme_high_risk'].get('total', 0)} providers)")

    print("Computing doctor shopping…")
    t = time.time()
    from services.beneficiary_analyzer import detect_doctor_shopping
    out["doctor_shopping"] = asyncio.run(detect_doctor_shopping(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s "
          f"({out['doctor_shopping'].get('total_flagged', 0)} flagged)")

    print("Computing billing top codes…")
    t = time.time()
    from routes.billing_codes import top_codes, diagnosis_flags
    out["billing_top_codes"] = asyncio.run(top_codes(limit=200, min_providers=1))
    print(f"  done in {time.time() - t:.0f}s ({out['billing_top_codes'].get('total_codes', 0)} codes)")

    print("Computing diagnosis flags…")
    t = time.time()
    out["billing_diagnosis_flags"] = asyncio.run(diagnosis_flags(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s ({out['billing_diagnosis_flags'].get('total', 0)} flagged)")

    print("Computing state billing trends…")
    t = time.time()
    from services.trend_divergence import _aggregate_billing_by_state_year
    out["billing_by_state_year"] = _aggregate_billing_by_state_year()
    print(f"  done in {time.time() - t:.0f}s ({len(out['billing_by_state_year'])} states)")

    print("Computing ownership networks…")
    t = time.time()
    from routes.ownership import compute_networks
    out["ownership_networks"] = compute_networks(providers)
    print(f"  done in {time.time() - t:.0f}s "
          f"({out['ownership_networks']['total_networks']} networks)")

    print("Writing HCPCS index parquet (powers per-code search on prod)…")
    t = time.time()
    _write_hcpcs_index(providers)
    print(f"  done in {time.time() - t:.0f}s")

    print("Writing network index parquet (powers instant /api/network/{npi})…")
    t = time.time()
    try:
        from scripts.build_network_index import build_network_index
        n_net = build_network_index()
        print(f"  {n_net:,} rows -> network_index.parquet in {time.time() - t:.0f}s")
    except SystemExit as e:
        # Built from the LOCAL dataset parquet; skip cleanly if it isn't present.
        print(f"  skipped: {e}")

    print("Rebuilding slim-cache risk scores from fresh full cache…")
    t = time.time()
    n_slim = rebuild_slim_scores(providers)
    print(f"  done in {time.time() - t:.0f}s ({n_slim:,} providers written to prescan_slim.json)")

    print("Backfilling slim-cache fields (specialty etc.)…")
    t = time.time()
    n_fixed = backfill_slim_fields(providers)
    print(f"  done in {time.time() - t:.0f}s ({n_fixed:,} providers updated)")

    print("Retraining ML anomaly model (Isolation Forest) on the fresh cache…")
    t = time.time()
    try:
        from services.ml_scorer import train_and_score
        ml = train_and_score()
        n_scored = ml.get("scored") or ml.get("provider_count") or len(ml.get("ml_scores") or {})
        print(f"  done in {time.time() - t:.0f}s "
              f"({n_scored} scored, {ml.get('anomaly_count', '?')} anomalies -> ml_scores.json)")
    except Exception as e:  # noqa: BLE001 — never let an optional layer block the refresh
        print(f"  ML retrain skipped: {e}")

    tmp = _OUT.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), default=str)
    tmp.replace(_OUT)
    size_mb = _OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {_OUT} ({size_mb:.1f} MB)")
    print("Next: upload to GCS ->")
    print('  gcloud storage cp backend/precomputed_analyses.json gs://medicaid-inspector-data/')
    print('  gcloud storage cp backend/hcpcs_index.parquet gs://medicaid-inspector-data/')
    print('  gcloud storage cp backend/network_index.parquet gs://medicaid-inspector-data/')
    return 0


if __name__ == "__main__":
    sys.exit(main())
