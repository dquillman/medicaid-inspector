"""
Build the deactivated-NPI lookup that powers the dormant `dead_npi_billing`
signal (a deactivated NPI still appearing in Medicaid billing = identity-theft /
unauthorized-billing lead — the highest-credibility, payer-agnostic indicator).

The NPPES bulk file carries an "NPI Deactivation Date" column. We scan it once,
keep only NPIs that are (a) deactivated and (b) actually present in our scanned
Medicaid population, and write a small backend/npi_deactivations.json
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


def main() -> int:
    import duckdb

    files = [f for f in glob.glob(EXTRACT_GLOB) if "FileHeader" not in f and "fileheader" not in f]
    if not files:
        print("ERROR: NPPES extract not found — run backfill_nppes_bulk.py first (it extracts the CSV).")
        return 1
    npidata = max(files, key=lambda f: pathlib.Path(f).stat().st_size)
    print(f"npidata: {pathlib.Path(npidata).name}")

    slim = json.loads((_BACKEND / "prescan_slim.json").read_text(encoding="utf-8"))
    npis = [p["npi"] for p in (slim.get("providers") or slim) if p.get("npi")]
    print(f"scanned NPIs: {len(npis):,}")

    con = duckdb.connect()
    con.execute("SET threads=4;")
    tgt = _BACKEND / "_deact_targets.csv"
    with open(tgt, "w", encoding="utf-8") as f:
        f.write("npi\n"); f.writelines(f"{n}\n" for n in npis)

    src = npidata.replace("\\", "/")
    tpath = str(tgt).replace("\\", "/")
    rows = con.execute(f"""
        SELECT n."NPI" AS npi, n."NPI Deactivation Date" AS dt
        FROM read_csv('{src}', header=true, all_varchar=true) n
        INNER JOIN read_csv('{tpath}', header=true, all_varchar=true) t ON n."NPI" = t.npi
        WHERE n."NPI Deactivation Date" IS NOT NULL AND n."NPI Deactivation Date" != ''
    """).fetchall()
    con.close()
    tgt.unlink(missing_ok=True)

    deacts = {npi: dt for npi, dt in rows}
    OUT.write_text(json.dumps(deacts, separators=(",", ":")), encoding="utf-8")
    print(f"deactivated NPIs in scanned population: {len(deacts):,} -> {OUT.name}")
    for npi, dt in list(deacts.items())[:10]:
        print(f"  {npi}  deactivated {dt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
