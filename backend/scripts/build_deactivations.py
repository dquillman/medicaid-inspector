"""
Build the deactivated-NPI lookup that powers the dormant `dead_npi_billing`
signal (a deactivated NPI still appearing in Medicaid billing = identity-theft /
unauthorized-billing lead — the highest-credibility, payer-agnostic indicator).

The NPPES bulk file carries an "NPI Deactivation Date" column. We scan it once,
keep only NPIs that are (a) deactivated and (b) present anywhere in the Medicaid
billing universe (ALL ~617k billing NPIs, not just the scanned subset — see the
target-list comment in main()), and write a small backend/npi_deactivations.json
({npi: deactivation_date}) that deactivation_store loads + GCS syncs.

Usage (from backend/):  G:\\Python311\\python.exe -X utf8 scripts\\build_deactivations.py
Reuses the already-extracted NPPES CSV under G:/temp/nppes_extract.
"""
import functools
import glob
import json
import pathlib
import sys

print = functools.partial(print, flush=True)  # noqa: A001
_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

EXTRACT_GLOB = "G:/temp/nppes_extract/npidata_pfile_*.csv"
OUT = _BACKEND / "npi_deactivations.json"
# NPIs that were deactivated and later REACTIVATED — {npi: [deact, react]}.
# Not dead today, so they stay out of npi_deactivations.json, but billing
# inside the closed window was still unauthorized. Only the per-se sweep uses it.
OUT_WINDOWS = _BACKEND / "npi_deactivation_windows.json"


def main() -> int:
    import duckdb

    files = [f for f in glob.glob(EXTRACT_GLOB) if "FileHeader" not in f and "fileheader" not in f]
    if not files:
        print("ERROR: NPPES extract not found — run backfill_nppes_bulk.py first (it extracts the CSV).")
        return 1
    npidata = max(files, key=lambda f: pathlib.Path(f).stat().st_size)
    print(f"npidata: {pathlib.Path(npidata).name}")

    con = duckdb.connect()
    con.execute("SET threads=4;")

    # Target = EVERY NPI that bills Medicaid, not just the scanned subset.
    # This used to INNER JOIN prescan_slim.json (106,660 NPIs above the $1M
    # scan cutoff), which meant a deactivated NPI billing $800k was invisible
    # twice over: below the scan cutoff AND absent from this lookup. A dead
    # NPI is per-se unauthorized billing at ANY dollar amount, so the dollar
    # cutoff has no business filtering it. Changed 2026-07-26.
    from data.duckdb_client import get_parquet_path
    parquet = get_parquet_path()
    print("collecting the full billing universe from the parquet…")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    npis = [r[0] for r in con.execute(f"""
        SELECT DISTINCT BILLING_PROVIDER_NPI_NUM
        FROM read_parquet('{parquet}')
        WHERE BILLING_PROVIDER_NPI_NUM IS NOT NULL
    """).fetchall()]
    print(f"billing NPIs (full universe): {len(npis):,}")

    tgt = _BACKEND / "_deact_targets.csv"
    with open(tgt, "w", encoding="utf-8") as f:
        f.write("npi\n"); f.writelines(f"{n}\n" for n in npis)

    src = npidata.replace("\\", "/")
    tpath = str(tgt).replace("\\", "/")
    # NPPES also carries "NPI Reactivation Date", which this script used to
    # ignore — so an NPI deactivated 03/17/2006 and reactivated 03/23/2006 (a
    # 2006 NPPES cleanup artifact, thousands of them) counted as permanently
    # dead. Measured 2026-07-26: 1,655 of 10,968 (15.1%) had been reactivated.
    # A reactivated NPI is ALIVE and must not feed dead_npi_billing.
    rows = con.execute(f"""
        SELECT n."NPI" AS npi,
               n."NPI Deactivation Date" AS dt,
               n."NPI Reactivation Date" AS rt
        FROM read_csv('{src}', header=true, all_varchar=true) n
        INNER JOIN read_csv('{tpath}', header=true, all_varchar=true) t ON n."NPI" = t.npi
        WHERE n."NPI Deactivation Date" IS NOT NULL AND n."NPI Deactivation Date" != ''
    """).fetchall()
    con.close()
    tgt.unlink(missing_ok=True)

    deacts: dict[str, str] = {}
    windows: dict[str, list[str]] = {}
    for npi, dt, rt in rows:
        if rt:
            # Deactivated then brought back. Currently active, so it is NOT a
            # dead NPI — but billing DURING the closed window was still
            # unauthorized, so keep the window for the per-se sweep to test.
            windows[npi] = [dt, rt]
        else:
            deacts[npi] = dt

    OUT.write_text(json.dumps(deacts, separators=(",", ":")), encoding="utf-8")
    OUT_WINDOWS.write_text(json.dumps(windows, separators=(",", ":")), encoding="utf-8")
    print(f"currently-deactivated NPIs billing Medicaid: {len(deacts):,} -> {OUT.name}")
    print(f"deactivated-then-reactivated (window only):  {len(windows):,} -> {OUT_WINDOWS.name}")
    for npi, dt in list(deacts.items())[:10]:
        print(f"  {npi}  deactivated {dt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
