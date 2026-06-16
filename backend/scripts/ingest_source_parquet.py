"""
CMS/HHS source ingest — the last manual piece of the data pipeline, automated.

Pulls the latest HHS "Medicaid Provider Spending by HCPCS" release and rebuilds
the canonical source parquet that everything else derives from.

SOURCE: Hugging Face dataset `HHS-Official/medicaid-provider-spending`
(the machine-readable mirror of opendata.hhs.gov; T-MSIS-derived, national,
NPI-level, free, NO DUA; Jan-2018 .. Dec-2024; ~238M rows). The HF Hub API needs
a FREE token — set the HF_TOKEN env var. You may also need to open the dataset
page once while signed in and accept its terms with the same account.
  Get a token: https://huggingface.co/settings/tokens  (read scope is enough)

SCHEMA: the HHS file uses TOTAL_PATIENTS / TOTAL_CLAIM_LINES; our canonical
parquet uses TOTAL_UNIQUE_BENEFICIARIES / TOTAL_CLAIMS. This script normalizes
to our schema (and tolerates either spelling, so it survives an HHS rename):

    BILLING_PROVIDER_NPI_NUM    VARCHAR
    SERVICING_PROVIDER_NPI_NUM  VARCHAR
    HCPCS_CODE                  VARCHAR
    CLAIM_FROM_MONTH            VARCHAR
    TOTAL_UNIQUE_BENEFICIARIES  BIGINT   (<- TOTAL_PATIENTS)
    TOTAL_CLAIMS                BIGINT   (<- TOTAL_CLAIM_LINES)
    TOTAL_PAID                  DOUBLE

MODES:
    check   - is there a newer HF revision than we last ingested? (cheap, no download)
    ingest  - download the source parquet(s), normalize, atomically swap into
              backend/data/medicaid-provider-spending.parquet, record the new
              source SHA in dataset_config.json.

After `ingest`, push it live with:  refresh-data.ps1 -Update -UploadParquet -Deploy
(or just `-Ingest -Update -Deploy`, which chains all of it).

Run with G:\\Python311\\python.exe (has duckdb + httpx). The refresh-data.ps1
wrapper does that for you.
"""
import argparse
import datetime as _dt
import functools
import json
import os
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
_DATA = _BACKEND / "data"
_TARGET = _DATA / "medicaid-provider-spending.parquet"
_CONFIG = _BACKEND / "dataset_config.json"

REPO = os.environ.get("MFI_SOURCE_REPO", "HHS-Official/medicaid-provider-spending")
_API = f"https://huggingface.co/api/datasets/{REPO}"
_RESOLVE = f"https://huggingface.co/datasets/{REPO}/resolve"

# Canonical output columns -> the list of accepted source spellings (first hit
# wins). Lets the ingest survive HHS renaming a column between releases.
_COLUMN_MAP = {
    "BILLING_PROVIDER_NPI_NUM":   ["BILLING_PROVIDER_NPI_NUM"],
    "SERVICING_PROVIDER_NPI_NUM": ["SERVICING_PROVIDER_NPI_NUM"],
    "HCPCS_CODE":                 ["HCPCS_CODE"],
    "CLAIM_FROM_MONTH":           ["CLAIM_FROM_MONTH"],
    "TOTAL_UNIQUE_BENEFICIARIES": ["TOTAL_UNIQUE_BENEFICIARIES", "TOTAL_PATIENTS", "TOTAL_BENEFICIARIES"],
    "TOTAL_CLAIMS":               ["TOTAL_CLAIMS", "TOTAL_CLAIM_LINES"],
    "TOTAL_PAID":                 ["TOTAL_PAID"],
}
_CAST = {
    "TOTAL_UNIQUE_BENEFICIARIES": "BIGINT",
    "TOTAL_CLAIMS": "BIGINT",
    "TOTAL_PAID": "DOUBLE",
}


# ── config ───────────────────────────────────────────────────────────────────
def _load_config() -> dict:
    if _CONFIG.exists():
        try:
            return json.loads(_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(cfg: dict) -> None:
    tmp = _CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(_CONFIG)


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


# ── Hugging Face Hub access ──────────────────────────────────────────────────
def _token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or None


def _require_token() -> str:
    tok = _token()
    if not tok:
        print("ERROR: no Hugging Face token. The HHS dataset's API requires one.")
        print("  1. Create a free read token: https://huggingface.co/settings/tokens")
        print(f"  2. Open https://huggingface.co/datasets/{REPO} while signed in and accept any terms.")
        print("  3. Set it:  $env:HF_TOKEN = '<token>'   (PowerShell)   then re-run.")
        raise SystemExit(2)
    return tok


def _get_meta(token: str) -> dict:
    import httpx
    r = httpx.get(_API, headers={"Authorization": f"Bearer {token}"},
                  follow_redirects=True, timeout=60.0)
    if r.status_code == 401:
        raise SystemExit("ERROR: HF returned 401 — token invalid, or you haven't accepted "
                         f"the dataset terms at https://huggingface.co/datasets/{REPO}")
    r.raise_for_status()
    return r.json()


def _parquet_files(meta: dict) -> list[str]:
    sibs = [s.get("rfilename", "") for s in meta.get("siblings", [])]
    pq = sorted(f for f in sibs if f.lower().endswith(".parquet"))
    return pq


def _download(token: str, revision: str, rfilename: str, dest: pathlib.Path) -> None:
    """Stream one file. HF redirects the resolve URL to a signed CDN URL — we
    must NOT forward the Authorization header to that CDN host, so resolve the
    redirect manually then fetch the final URL bare."""
    import httpx
    url = f"{_RESOLVE}/{revision}/{rfilename}"
    auth = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=None, follow_redirects=False) as client:
        r = client.get(url, headers=auth)
        while r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers["location"]
            # Same-host (huggingface.co) redirects keep auth; CDN hosts get none.
            hdrs = auth if loc.startswith("https://huggingface.co/") else {}
            r = client.get(loc, headers=hdrs)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        t = time.time()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            for chunk in r.iter_bytes(chunk_size=1_048_576):
                fh.write(chunk)
                done += len(chunk)
    secs = max(time.time() - t, 0.001)
    print(f"    {rfilename}: {done/1e9:.2f} GB in {secs:.0f}s ({done/secs/1e6:.1f} MB/s)")


# ── transform ────────────────────────────────────────────────────────────────
def _build_select(con, src_glob: str) -> str:
    cols = {r[0].upper(): r[0] for r in
            con.execute(f"DESCRIBE SELECT * FROM read_parquet({src_glob}) LIMIT 0").fetchall()}
    selects, missing = [], []
    for out_col, candidates in _COLUMN_MAP.items():
        hit = next((cols[c.upper()] for c in candidates if c.upper() in cols), None)
        if hit is None:
            missing.append(f"{out_col} (looked for {candidates})")
            continue
        cast = _CAST.get(out_col)
        expr = f'CAST("{hit}" AS {cast})' if cast else f'"{hit}"'
        selects.append(f'{expr} AS {out_col}')
    if missing:
        raise SystemExit(
            "ERROR: source schema drifted — could not map these output columns:\n  "
            + "\n  ".join(missing)
            + f"\n  Source columns present: {sorted(cols)}\n"
              "  Update _COLUMN_MAP in this script to match the new HHS schema."
        )
    return ",\n            ".join(selects)


def _transform(downloaded: list[pathlib.Path]) -> int:
    import duckdb
    src_list = "[" + ",".join("'" + str(p).replace("\\", "/") + "'" for p in downloaded) + "]"
    out_tmp = _DATA / "medicaid-provider-spending.parquet.tmp"
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    select_sql = _build_select(con, src_list)
    print("  transforming -> canonical schema (renaming columns, zstd)…")
    t = time.time()
    con.execute(f"""
        COPY (
            SELECT
            {select_sql}
            FROM read_parquet({src_list})
        ) TO '{str(out_tmp).replace(chr(92), "/")}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{str(out_tmp).replace(chr(92), '/')}')").fetchone()[0]
    con.close()
    print(f"    {n:,} rows in {time.time() - t:.0f}s")
    # Atomic swap.
    if _TARGET.exists():
        _TARGET.unlink()
    out_tmp.rename(_TARGET)
    return n


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_check() -> int:
    token = _require_token()
    cfg = _load_config()
    meta = _get_meta(token)
    sha, lm = meta.get("sha"), meta.get("lastModified")
    have = cfg.get("source_sha")
    print(f"Source: HF {REPO}")
    print(f"  latest revision : {sha}  (lastModified {lm})")
    print(f"  last ingested   : {have or '(never)'}  (on {cfg.get('detected_date') or '?'})")
    if have == sha:
        print("  => UP TO DATE — local source matches the latest HF release.")
        return 0
    print("  => NEW RELEASE AVAILABLE — run:  refresh-data.ps1 -Ingest -Update -Deploy")
    return 0


def cmd_ingest(force: bool) -> int:
    token = _require_token()
    cfg = _load_config()
    meta = _get_meta(token)
    sha = meta.get("sha")
    if sha and sha == cfg.get("source_sha") and not force:
        print(f"Already at the latest source revision ({sha}). Use --force to re-ingest anyway.")
        return 0

    files = _parquet_files(meta)
    if not files:
        raise SystemExit("ERROR: no .parquet files found in the HF dataset. "
                         f"Files: {[s.get('rfilename') for s in meta.get('siblings', [])]}")
    print(f"Downloading {len(files)} parquet file(s) from {REPO}@{sha} …")
    tmpdir = _DATA / "_source_ingest_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for f in files:
        dest = tmpdir / pathlib.Path(f).name
        _download(token, sha or "main", f, dest)
        downloaded.append(dest)

    n = _transform(downloaded)

    # Clean temp downloads.
    for p in downloaded:
        try:
            p.unlink()
        except OSError:
            pass
    try:
        tmpdir.rmdir()
    except OSError:
        pass

    cfg.update({
        "url": cfg.get("url"),
        "source_repo": REPO,
        "source_sha": sha,
        "source_last_modified": meta.get("lastModified"),
        "row_count": n,
        "detected_date": _now_iso(),
        "last_checked": _now_iso(),
        "last_check_error": None,
    })
    _save_config(cfg)
    size_gb = _TARGET.stat().st_size / 1e9
    print(f"\nDONE — {_TARGET.name} rebuilt ({n:,} rows, {size_gb:.2f} GB), source_sha={sha}")
    print("Next: push it live ->  refresh-data.ps1 -Update -UploadParquet -Deploy")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest the latest HHS Medicaid source parquet")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", help="is a newer HF release available? (no download)")
    ing = sub.add_parser("ingest", help="download + normalize + swap in the new source parquet")
    ing.add_argument("--force", action="store_true", help="re-ingest even if the SHA is unchanged")
    args = ap.parse_args()
    if args.cmd == "ingest":
        return cmd_ingest(args.force)
    return cmd_check()  # default


if __name__ == "__main__":
    sys.exit(main())
