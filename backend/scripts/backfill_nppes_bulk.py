"""
Backfill taxonomy (specialty) + authorized officials from the NPPES bulk file.

The cached NPPES blobs were enriched with an older format that lacked
taxonomy and authorized_official (50/106k coverage), which blanked the
Specialty Benchmark and Ownership Networks. The monthly NPPES Data
Dissemination file has both for every NPI — one pass fixes the full cache,
then the slim cache and ownership precompute get regenerated from it.

Inputs (downloaded beforehand):
    G:/temp/nppes_june2026.zip   (NPPES Data Dissemination, ~1 GB zip)
    G:/temp/nucc_taxonomy.csv    (NUCC taxonomy code -> display name)

Usage:
    G:\\Python311\\python.exe -X utf8 backend/scripts/backfill_nppes_bulk.py
"""
import csv
import functools
import json
import pathlib
import sys
import time
import zipfile

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

ZIP_PATH = pathlib.Path("G:/temp/nppes_june2026.zip")
NUCC_PATH = pathlib.Path("G:/temp/nucc_taxonomy.csv")
EXTRACT_DIR = pathlib.Path("G:/temp/nppes_extract")


def load_nucc() -> dict[str, str]:
    """Taxonomy code -> human-readable name."""
    names: dict[str, str] = {}
    with open(NUCC_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("Code") or "").strip()
            if not code:
                continue
            display = (row.get("Display Name") or "").strip()
            if not display:
                cls = (row.get("Classification") or "").strip()
                spec = (row.get("Specialization") or "").strip()
                display = f"{cls} {spec}".strip()
            names[code] = display
    return names


def extract_npidata() -> pathlib.Path:
    """Pull the main npidata_pfile CSV out of the dissemination zip."""
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as z:
        member = next(
            n for n in z.namelist()
            if n.startswith("npidata_pfile_") and n.endswith(".csv")
            and "FileHeader" not in n and "fileheader" not in n
        )
        out = EXTRACT_DIR / member
        if out.exists() and out.stat().st_size > 1_000_000_000:
            print(f"  already extracted: {out.name}")
            return out
        print(f"  extracting {member} (this is ~10 GB)…")
        z.extract(member, EXTRACT_DIR)
    return out


def query_bulk(npidata: pathlib.Path, npis: list[str]) -> dict[str, dict]:
    """One DuckDB pass over the bulk CSV, filtered to our NPIs."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET threads=4;")
    npi_csv = EXTRACT_DIR / "_target_npis.csv"
    with open(npi_csv, "w", encoding="utf-8") as f:
        f.write("npi\n")
        f.writelines(f"{n}\n" for n in npis)

    src = str(npidata).replace("\\", "/")
    tgt = str(npi_csv).replace("\\", "/")

    # Primary taxonomy = first slot whose Primary Switch is 'Y' (X = unknown
    # legacy value, treat as primary too), falling back to slot 1.
    tax_case = "CASE "
    for i in range(1, 16):
        tax_case += (
            f"WHEN \"Healthcare Provider Primary Taxonomy Switch_{i}\" IN ('Y','X') "
            f"THEN \"Healthcare Provider Taxonomy Code_{i}\" "
        )
    tax_case += "ELSE \"Healthcare Provider Taxonomy Code_1\" END"

    rows = con.execute(f"""
        SELECT
            n."NPI"                                                  AS npi,
            n."Entity Type Code"                                     AS entity_type,
            {tax_case}                                               AS taxonomy_code,
            n."Authorized Official Last Name"                        AS ao_last,
            n."Authorized Official First Name"                       AS ao_first,
            n."Authorized Official Title or Position"                AS ao_title,
            n."Provider Organization Name (Legal Business Name)"     AS org_name,
            n."Provider Last Name (Legal Name)"                      AS ind_last,
            n."Provider First Name"                                  AS ind_first,
            n."Provider Business Practice Location Address City Name"  AS city,
            n."Provider Business Practice Location Address State Name" AS state,
            n."Provider Business Practice Location Address Postal Code" AS zip
        FROM read_csv('{src}', header=true, all_varchar=true) n
        INNER JOIN read_csv('{tgt}', header=true, all_varchar=true) t
            ON n."NPI" = t.npi
    """).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    npi_csv.unlink(missing_ok=True)
    return {r[0]: dict(zip(cols, r)) for r in rows}


def main() -> int:
    t_all = time.time()
    if not ZIP_PATH.exists() or not NUCC_PATH.exists():
        print("ERROR: download the NPPES zip and NUCC csv first.")
        return 1

    print("Loading NUCC taxonomy names…")
    nucc = load_nucc()
    print(f"  {len(nucc):,} taxonomy codes")

    print("Extracting bulk npidata CSV…")
    t = time.time()
    npidata = extract_npidata()
    print(f"  done in {time.time() - t:.0f}s")

    print("Loading full prescan cache…")
    t = time.time()
    from core.store import load_prescanned_from_disk, get_prescanned
    if not load_prescanned_from_disk():
        print("ERROR: could not load prescan_cache.json")
        return 1
    providers = get_prescanned()
    print(f"  {len(providers):,} providers in {time.time() - t:.0f}s")

    print("Querying bulk file for our NPIs (one ~10 GB scan)…")
    t = time.time()
    bulk = query_bulk(npidata, [p["npi"] for p in providers if p.get("npi")])
    print(f"  matched {len(bulk):,} NPIs in {time.time() - t:.0f}s")

    print("Merging into full cache…")
    n_tax = n_ao = 0
    for p in providers:
        rec = bulk.get(p.get("npi"))
        if not rec:
            continue
        nppes = p.get("nppes")
        if not isinstance(nppes, dict):
            nppes = {}
            p["nppes"] = nppes

        code = (rec.get("taxonomy_code") or "").strip()
        if code and not (nppes.get("taxonomy") or {}).get("description"):
            nppes["taxonomy"] = {"code": code, "description": nucc.get(code, code)}
            n_tax += 1

        ao_name = f"{(rec.get('ao_first') or '').strip()} {(rec.get('ao_last') or '').strip()}".strip()
        if ao_name and not (nppes.get("authorized_official") or {}).get("name"):
            nppes["authorized_official"] = {
                "name": ao_name,
                "title": (rec.get("ao_title") or "").strip(),
            }
            n_ao += 1

        et = (rec.get("entity_type") or "").strip()
        if et and not nppes.get("entity_type"):
            nppes["entity_type"] = "Organization" if et == "2" else "Individual"

        if not nppes.get("name"):
            org = (rec.get("org_name") or "").strip()
            ind = f"{(rec.get('ind_first') or '').strip()} {(rec.get('ind_last') or '').strip()}".strip()
            if org or ind:
                nppes["name"] = org or ind

        addr = nppes.get("address")
        if not isinstance(addr, dict):
            addr = {}
            nppes["address"] = addr
        for src_k, dst_k in (("city", "city"), ("state", "state"), ("zip", "zip")):
            v = (rec.get(src_k) or "").strip()
            if v and not (addr.get(dst_k) or "").strip():
                addr[dst_k] = v

    print(f"  taxonomy filled: {n_tax:,} | authorized officials filled: {n_ao:,}")

    print("Writing full cache back to disk (1.4 GB)…")
    t = time.time()
    from core.store import save_to_disk
    save_to_disk()
    print(f"  done in {time.time() - t:.0f}s")

    print("Backfilling slim cache fields…")
    t = time.time()
    from scripts.precompute_analyses import backfill_slim_fields
    n_slim = backfill_slim_fields(providers)
    print(f"  {n_slim:,} slim records updated in {time.time() - t:.0f}s")

    print(f"ALL DONE in {(time.time() - t_all) / 60:.1f} min")
    print("Next: rerun precompute_analyses.py (ownership networks), then upload")
    print("  prescan_slim.json (gzip) + precomputed_analyses.json to GCS and bounce prod.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
