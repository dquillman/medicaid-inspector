"""
Backfill practice-location address + enumeration date into prescan_slim.json.

Why
---
Three fraud signals were measured DARK across all 106,660 scanned providers
(2026-07-26) purely because their inputs are absent from the slim cache:

  * address_cluster_risk    needs nppes.address.line1 + .zip  -> 0/106,660
  * geographic_impossibility needs nppes.address.state        -> 0/106,660
  * new_provider_explosion  needs nppes.enumeration_date      -> 0/106,660

compute_address_clusters() therefore returns an empty dict and every provider
scores 0 with "No NPPES address data available". The docstrings call this "a
known slim-cache limitation", but backfill_slim_officials.py already proved the
slim cache can carry NPPES fields — it just copies from prescan_cache.json,
which is a stub on this workstation. So this script goes to the authoritative
source instead: the NPPES bulk dissemination CSV, same as build_deactivations.py.

PRACTICE LOCATION, not mailing address. Co-location clustering is about where
providers physically operate; a shared mailing address (a billing service, a
registered agent) is a different and much noisier signal.

Keeps the slim cache slim: four scalar fields, nothing else.

Usage (from backend/):
    G:\\Python311\\python.exe -X utf8 scripts\\backfill_slim_nppes_fields.py

Then rescore (signals are evaluated at scan time and stored as flags, so the
backfill alone changes nothing), and upload:
    gcloud storage cp prescan_slim.json gs://medicaid-inspector-data/
"""
import functools
import glob
import json
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

EXTRACT_GLOB = "G:/temp/nppes_extract/npidata_pfile_*.csv"
SLIM = _BACKEND / "prescan_slim.json"

COL_LINE1 = "Provider First Line Business Practice Location Address"
COL_ZIP   = "Provider Business Practice Location Address Postal Code"
COL_STATE = "Provider Business Practice Location Address State Name"
COL_ENUM  = "Provider Enumeration Date"


def main() -> int:
    import duckdb

    files = [f for f in glob.glob(EXTRACT_GLOB)
             if "FileHeader" not in f and "fileheader" not in f]
    if not files:
        print("ERROR: NPPES extract not found — run backfill_nppes_bulk.py first.")
        return 1
    npidata = max(files, key=lambda f: pathlib.Path(f).stat().st_size)
    print(f"npidata: {pathlib.Path(npidata).name}")

    if not SLIM.exists():
        print("ERROR: prescan_slim.json not found in backend/")
        return 1

    t0 = time.time()
    print("loading slim cache…")
    slim = json.loads(SLIM.read_text(encoding="utf-8"))
    provs = slim if isinstance(slim, list) else slim.get("providers", [])
    npis = [p["npi"] for p in provs if p.get("npi")]
    before_size = SLIM.stat().st_size
    print(f"  {len(provs):,} providers ({time.time() - t0:.0f}s)")

    con = duckdb.connect()
    con.execute("SET threads=4;")
    tgt = _BACKEND / "_nppes_backfill_targets.csv"
    with open(tgt, "w", encoding="utf-8") as f:
        f.write("npi\n")
        f.writelines(f"{n}\n" for n in npis)

    src = npidata.replace("\\", "/")
    tpath = str(tgt).replace("\\", "/")
    print("joining against the NPPES bulk file…")
    t1 = time.time()
    rows = con.execute(f"""
        SELECT n."NPI" AS npi,
               n."{COL_LINE1}" AS line1,
               n."{COL_ZIP}"   AS zip,
               n."{COL_STATE}" AS state,
               n."{COL_ENUM}"  AS enumerated
        FROM read_csv('{src}', header=true, all_varchar=true) n
        INNER JOIN read_csv('{tpath}', header=true, all_varchar=true) t
          ON n."NPI" = t.npi
    """).fetchall()
    con.close()
    tgt.unlink(missing_ok=True)
    print(f"  {len(rows):,} NPPES rows matched ({time.time() - t1:.0f}s)")

    by_npi = {r[0]: r for r in rows}

    addr_added = enum_added = 0
    for p in provs:
        r = by_npi.get(p.get("npi"))
        if not r:
            continue
        _, line1, zipc, state, enumerated = r
        nppes = p.setdefault("nppes", {})
        line1 = (line1 or "").strip()
        zipc = (zipc or "").strip()
        state = (state or "").strip()
        if line1 or zipc or state:
            addr = nppes.setdefault("address", {})
            if line1: addr["line1"] = line1
            # compute_address_clusters keys on zip[:5]; store the 5-digit form so
            # a ZIP+4 and its 5-digit twin land in the SAME cluster.
            if zipc: addr["zip"] = zipc[:5]
            if state: addr["state"] = state
            addr_added += 1
        enumerated = (enumerated or "").strip()
        if enumerated:
            nppes["enumeration_date"] = enumerated
            enum_added += 1

    tmp = SLIM.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slim, f, separators=(",", ":"), default=str)
    tmp.replace(SLIM)
    after_size = SLIM.stat().st_size

    print()
    print(f"backfilled address for   {addr_added:,} providers")
    print(f"backfilled enum date for {enum_added:,} providers")
    print(f"slim size {before_size/1048576:.1f}MB -> {after_size/1048576:.1f}MB "
          f"(+{(after_size-before_size)/1048576:.1f}MB)")
    print(f"total {time.time() - t0:.0f}s")
    print()
    print("NOT DONE YET: signals are stored as flags at scan time, so this changes")
    print("nothing until a rescore. Then upload prescan_slim.json to GCS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
