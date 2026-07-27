"""
Build missing_npis.json — the artifact behind the Fraud Brain "Add missing" button.

Why an artifact instead of a live query: computing the rank gap means a
GROUP-BY over all 227M rows ordered by total_paid. On the workstation (local
parquet) that is ~60s; on prod (remote parquet over httpfs) the preview
endpoint 503'd after 38s — measured 2026-07-26, and the button silently hid
itself because its data never arrived. So the diff is computed here, against
the local parquet, and shipped via GCS like perse_leads.json. Prod only reads
the file.

Staleness is self-correcting: run_missing_scan re-checks every NPI against the
live cache before scanning, so an NPI scanned after this file was built is
skipped, never duplicated.

Usage (from backend/):
    G:\\Python311\\python.exe -X utf8 scripts\\build_missing_npis.py
Then:
    gcloud storage cp missing_npis.json gs://medicaid-inspector-data/
"""
import functools
import json
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

OUT = _BACKEND / "missing_npis.json"


def main() -> int:
    import duckdb
    from data.duckdb_client import get_parquet_path

    t0 = time.time()
    slim = json.loads((_BACKEND / "prescan_slim.json").read_text(encoding="utf-8"))
    cached = {p["npi"] for p in slim.get("providers", []) if p.get("npi")}
    print(f"scan cache: {len(cached):,} NPIs")

    con = duckdb.connect()
    con.execute("SET threads=4;")
    rows = con.execute(f"""
        SELECT BILLING_PROVIDER_NPI_NUM AS npi, SUM(TOTAL_PAID) AS paid
        FROM read_parquet('{get_parquet_path()}')
        GROUP BY 1 ORDER BY paid DESC LIMIT {len(cached)}
    """).fetchall()
    con.close()
    rank_gap = [r[0] for r in rows if r[0] not in cached]
    print(f"rank gap (unscanned inside today's top {len(cached):,}): {len(rank_gap):,}")

    perse: list[str] = []
    try:
        leads = json.loads((_BACKEND / "perse_leads.json").read_text(encoding="utf-8"))
        perse = [r["npi"] for r in leads.get("leads", [])
                 if r.get("in_scan_cache") is False and r.get("npi") and r["npi"] not in cached]
        print(f"per-se leads outside the cache: {len(perse):,}")
    except (OSError, ValueError) as e:
        print(f"WARN: perse_leads.json unavailable ({e}) — artifact will carry the rank gap only")

    npis = [n for n in dict.fromkeys([*rank_gap, *perse])]
    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cached_at_build": len(cached),
        "rank_gap": rank_gap,
        "perse": perse,
        "npis": npis,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(npis):,} NPIs -> {OUT.name} ({OUT.stat().st_size // 1024} KB, {time.time() - t0:.0f}s)")
    print("upload: gcloud storage cp missing_npis.json gs://medicaid-inspector-data/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
