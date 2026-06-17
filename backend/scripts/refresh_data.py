"""
Data-refresh control center for Medicaid Inspector.

Two jobs, one place:

  * STATUS  — show, at a glance, which data artifacts are current vs stale and
    whether prod (GCS) matches your workstation.  `python refresh_data.py status`
  * UPDATE  — rebuild every derived artifact from the source parquet, refresh the
    prod-served slim cache, and upload to GCS.  `python refresh_data.py update`

Why a workstation tool (not an in-app button): the full scan cache is ~1.4 GB
and OOMs the 2 GiB Cloud Run container, and the index builds need the local
parquet + duckdb. So the heavy rebuild has to run here, on the box with the data.

Run with the interpreter that has the full backend deps + GCS auth — on Dave's
machine that's G:\\Python311\\python.exe (duckdb, sklearn, google-cloud-storage,
and working application-default credentials). The `refresh-data.ps1` wrapper
picks it for you.

The pipeline order (UPDATE):
    1. (optional --download) mirror the latest parquet from GCS to local
    2. rebuild_prescan_bulk.py   -> prescan_cache.json (full, fresh scores)
    3. precompute_analyses.py    -> precomputed_analyses.json, hcpcs_index.parquet,
                                    network_index.parquet, AND rebuilds the slim
                                    cache scores (so prod reflects the new run)
    4. (optional) build_deactivations.py -> npi_deactivations.json
    5. upload the synced artifacts to GCS
Deploy (a fresh Cloud Run revision to force the artifact re-download) is handled
by refresh-data.ps1 -Deploy, since it needs the gcloud workaround.
"""
import argparse
import datetime as _dt
import functools
import glob
import json
import os
import pathlib
import subprocess
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
_SCRIPTS = _BACKEND / "scripts"
_BUCKET = os.environ.get("GCS_BUCKET", "medicaid-inspector-data")
_NPPES_EXTRACT_GLOB = "G:/temp/nppes_extract/npidata_pfile_*.csv"

# kind: source = the parquet everything derives from; derived = built from it;
# external = sourced elsewhere (NPPES) so not compared against the parquet.
# syncable = uploaded to GCS during `update` (the full cache + parquet are huge
# and handled specially, so they're not in the default upload set).
ARTIFACTS = [
    {"key": "parquet",      "path": "data/medicaid-provider-spending.parquet", "blob": "medicaid-provider-spending.parquet", "kind": "source",   "syncable": False, "desc": "Source Medicaid claims (T-MSIS)"},
    {"key": "full_cache",   "path": "prescan_cache.json",        "blob": "prescan_cache.json",        "kind": "derived",  "syncable": False, "desc": "Full scan cache (local primary, ~1.4 GB)"},
    {"key": "slim_cache",   "path": "prescan_slim.json",         "blob": "prescan_slim.json",         "kind": "derived",  "syncable": True,  "desc": "Slim cache PROD serves"},
    {"key": "analyses",     "path": "precomputed_analyses.json", "blob": "precomputed_analyses.json", "kind": "derived",  "syncable": True,  "desc": "Precomputed heavy analyses"},
    {"key": "hcpcs_index",  "path": "hcpcs_index.parquet",       "blob": "hcpcs_index.parquet",       "kind": "derived",  "syncable": True,  "desc": "Per-code search index"},
    {"key": "network_index","path": "network_index.parquet",     "blob": "network_index.parquet",     "kind": "derived",  "syncable": True,  "desc": "Ego-network index (fast /api/network)"},
    {"key": "deactivations","path": "npi_deactivations.json",    "blob": "npi_deactivations.json",    "kind": "external", "syncable": True,  "desc": "Deactivated-NPI lookup (NPPES)"},
]

_TOLERANCE_SEC = 120  # ignore sub-2-minute clock skew between local mtime and GCS


# ── helpers ──────────────────────────────────────────────────────────────────
def _local_meta(rel: str):
    p = _BACKEND / rel
    if not p.exists():
        return None
    st = p.stat()
    return {"mtime": _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc), "size": st.st_size}


def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(_BUCKET)


def _gcs_meta(bucket, blob_name: str):
    try:
        blob = bucket.get_blob(blob_name)
        if blob is None:
            return None
        return {"mtime": blob.updated, "size": blob.size or 0}
    except Exception as e:
        return {"error": str(e)[:60]}


def _fmt_size(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _fmt_age(dt) -> str:
    if dt is None:
        return "—"
    secs = (_dt.datetime.now(tz=_dt.timezone.utc) - dt).total_seconds()
    if secs < 0:
        secs = 0
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h ago"
    if h:
        return f"{h}h {m}m ago"
    return f"{m}m ago"


def _verdict(art, local, gcs, parquet_local):
    """Return (marker, note). Markers are ASCII so they render in any console."""
    if local is None and (gcs is None or "error" in (gcs or {})):
        return "[MISSING]", "absent locally and in GCS"
    if local is None:
        return "[GCS-ONLY]", "in GCS but not on this box (run --download or update)"

    # Source parquet: it IS the source, so compare local vs GCS only.
    if art["kind"] == "source":
        if gcs is None:
            return "[LOCAL-ONLY]", "not yet uploaded to GCS"
        delta = (local["mtime"] - gcs["mtime"]).total_seconds()
        if delta > _TOLERANCE_SEC:
            return "[LOCAL-AHEAD]", "newer source on this box — upload with update --upload-parquet"
        if delta < -_TOLERANCE_SEC:
            return "[GCS-AHEAD]", "newer source in GCS — run update --download"
        return "[OK]", "local matches GCS"

    # Derived/external: stale if older than the source parquet.
    if parquet_local and art["kind"] == "derived" and local["mtime"] < parquet_local["mtime"] - _dt.timedelta(seconds=_TOLERANCE_SEC):
        return "[STALE]", "older than the source parquet — rebuild"

    if art["syncable"]:
        if gcs is None:
            return "[NEEDS-UPLOAD]", "built locally, not in GCS"
        delta = (local["mtime"] - gcs["mtime"]).total_seconds()
        if delta > _TOLERANCE_SEC:
            return "[NEEDS-UPLOAD]", "local newer than GCS — upload"
        if delta < -_TOLERANCE_SEC:
            return "[GCS-AHEAD]", "GCS newer than local"
    return "[OK]", "current"


# ── status ───────────────────────────────────────────────────────────────────
def cmd_status() -> int:
    print(f"Data freshness — bucket gs://{_BUCKET}\n")
    try:
        bucket = _bucket()
        gcs_ok = True
    except Exception as e:
        print(f"  (GCS unreachable: {e}; showing local only)\n")
        bucket = None
        gcs_ok = False

    parquet_local = _local_meta("data/medicaid-provider-spending.parquet")

    hdr = f"{'ARTIFACT':<16}{'STATUS':<15}{'LOCAL':<22}{'GCS':<22}{'SIZE':<10}DETAIL"
    print(hdr)
    print("-" * len(hdr))
    worst = 0
    for art in ARTIFACTS:
        local = _local_meta(art["path"])
        gcs = _gcs_meta(bucket, art["blob"]) if gcs_ok else None
        marker, note = _verdict(art, local, gcs, parquet_local)
        local_s = _fmt_age(local["mtime"]) if local else "missing"
        gcs_s = ("—" if not gcs_ok else "missing" if gcs is None else f"err:{gcs['error']}" if "error" in gcs else _fmt_age(gcs["mtime"]))
        size_s = _fmt_size(local["size"]) if local else "—"
        if marker in ("[MISSING]", "[STALE]"):
            worst = max(worst, 2)
        elif marker not in ("[OK]",):
            worst = max(worst, 1)
        print(f"{art['key']:<16}{marker:<15}{local_s:<22}{gcs_s:<22}{size_s:<10}{art['desc']}  ({note})")

    # Extra context from the analyses file's own stamp.
    a = _BACKEND / "precomputed_analyses.json"
    if a.exists():
        try:
            with open(a, encoding="utf-8") as f:
                meta = json.load(f)
            print(f"\n  precomputed_analyses: generated_at={meta.get('generated_at','?')} "
                  f"provider_count={meta.get('provider_count','?')}")
        except Exception:
            pass

    # Source release check — is HHS publishing a newer dataset than we ingested?
    # Needs HF_TOKEN; must never crash the status board.
    try:
        import ingest_source_parquet as ing
        tok = ing._token()
        if not tok:
            print("\n  source release: set HF_TOKEN to check HHS for a newer dataset release"
                  " (refresh-data.ps1 -CheckSource)")
        else:
            cfg = ing._load_config()
            meta = ing._get_meta(tok)
            sha, have = meta.get("sha"), cfg.get("source_sha")
            if have == sha:
                print(f"\n  source release: UP TO DATE (HF {ing.REPO} @ {sha})")
            else:
                print(f"\n  source release: NEW AVAILABLE — HF latest {sha}, last ingested {have or 'never'}"
                      "\n    run: refresh-data.ps1 -Ingest -Update -Deploy")
    except (Exception, SystemExit) as e:  # noqa: BLE001
        print(f"\n  source release: check skipped ({type(e).__name__})")

    print("\nLegend: [OK] current  [STALE] older than source  [NEEDS-UPLOAD] local ahead of GCS"
          "  [GCS-AHEAD]/[GCS-ONLY] prod ahead  [MISSING] absent")
    print("To rebuild + upload:  refresh-data.ps1 -Update      (add -Deploy to ship a fresh revision)")
    return 0


# ── update ───────────────────────────────────────────────────────────────────
def _run_step(title: str, argv: list[str]) -> None:
    print(f"\n{'='*70}\n  {title}\n{'='*70}")
    t = time.time()
    # Use the same interpreter running this orchestrator; force UTF-8 stdout.
    proc = subprocess.run([sys.executable, "-X", "utf8", *argv], cwd=str(_BACKEND))
    if proc.returncode != 0:
        raise SystemExit(f"STEP FAILED ({proc.returncode}): {title}")
    print(f"  -> {title} done in {time.time() - t:.0f}s")


def _upload(keys: list[str]) -> None:
    print(f"\n{'='*70}\n  Uploading to gs://{_BUCKET}\n{'='*70}")
    bucket = _bucket()
    for art in ARTIFACTS:
        if art["key"] not in keys:
            continue
        p = _BACKEND / art["path"]
        if not p.exists():
            print(f"  skip {art['blob']} (not built)")
            continue
        t = time.time()
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"  uploading {art['blob']} ({size_mb:.1f} MB)…")
        bucket.blob(art["blob"]).upload_from_filename(str(p))
        print(f"    done in {time.time() - t:.0f}s")


def cmd_update(args) -> int:
    parquet = _BACKEND / "data" / "medicaid-provider-spending.parquet"

    if args.download:
        _run_step("Mirror latest parquet from GCS", [str(_SCRIPTS / "download_medicaid_parquet.py")])
    if not (parquet.exists() and parquet.stat().st_size > 1_000_000):
        print(f"ERROR: source parquet missing at {parquet}.\n"
              "  Supply a fresh parquet there, or re-run with --download to pull it from GCS.")
        return 1

    if not args.yes:
        print("This rebuilds the full scan cache, all indexes, and the prod slim cache,")
        print("then uploads them to GCS. Expect ~20-60 min. Re-run with --yes to proceed.")
        return 0

    t0 = time.time()
    _run_step("1/4  Full scan rebuild (prescan_cache.json)", [str(_SCRIPTS / "rebuild_prescan_bulk.py")])
    _run_step("2/4  Precompute analyses + indexes + slim scores", [str(_SCRIPTS / "precompute_analyses.py")])

    upload_keys = [a["key"] for a in ARTIFACTS if a["syncable"]]
    if args.with_deactivations:
        if glob.glob(_NPPES_EXTRACT_GLOB):
            _run_step("3/4  Deactivated-NPI lookup", [str(_SCRIPTS / "build_deactivations.py")])
        else:
            print(f"\n  3/4  Skipping deactivations — NPPES extract not found at {_NPPES_EXTRACT_GLOB}")
            print("       (run backfill_nppes_bulk.py first to refresh it)")
            upload_keys = [k for k in upload_keys if k != "deactivations"]
    else:
        upload_keys = [k for k in upload_keys if k != "deactivations"]

    if args.upload_parquet:
        upload_keys = ["parquet", *upload_keys]

    _upload(upload_keys)

    print(f"\nALL DONE in {(time.time() - t0)/60:.1f} min. Artifacts uploaded to gs://{_BUCKET}.")
    print("Prod picks them up on the next cold start. To force it now: refresh-data.ps1 -Deploy")
    return 0


# Exit codes the PowerShell wrapper keys off of (keep in sync with refresh-data.ps1):
SMART_DID_WORK = 0     # rebuilt something -> wrapper should deploy
SMART_NEEDS_TOKEN = 2  # no/invalid Hugging Face token -> wrapper shows setup steps
SMART_UP_TO_DATE = 10  # nothing to do -> wrapper skips the deploy


def cmd_smart() -> int:
    """Do ONLY what's needed: check the source + derived freshness, then either
    say 'already up to date' (fast, no work) or download/rebuild/upload exactly
    what changed. The PowerShell wrapper deploys afterward iff we did work.

    Decision:
      * new government release          -> ingest + full rebuild + upload
      * source same, derived data stale -> full rebuild + upload (refresh scores)
      * everything current              -> nothing to do
    """
    print("Checking what needs updating…\n")

    # 1) Token must be present and valid before we promise anything.
    import ingest_source_parquet as ing
    if not ing._token():
        print("Setup needed: no Hugging Face token saved (see HOW-TO-UPDATE.txt).")
        return SMART_NEEDS_TOKEN
    try:
        meta = ing._get_meta(ing._token())
    except (SystemExit, Exception) as e:  # noqa: BLE001
        print(f"Setup needed: {e}")
        return SMART_NEEDS_TOKEN

    sha = meta.get("sha")
    cfg = ing._load_config()
    source_new = bool(sha) and sha != cfg.get("source_sha")

    # 2) Is our derived (prod-served) data stale by the monthly cadence?
    derived_stale = True
    try:
        from services.precomputed_store import get_generated_at
        from datetime import datetime, timezone
        ga = get_generated_at()
        if ga:
            age_days = (datetime.now(timezone.utc)
                        - datetime.fromisoformat(ga.replace("Z", "+00:00"))).days
            derived_stale = age_days > 35
            print(f"  derived data: rebuilt {age_days} days ago")
    except Exception:
        pass
    print(f"  government source: {'NEW release available' if source_new else 'unchanged'}")

    if not source_new and not derived_stale:
        print("\nEverything is already up to date — nothing to do.")
        return SMART_UP_TO_DATE

    # 3) Do exactly what's needed.
    t0 = time.time()
    if source_new:
        _run_step("Download the new government data", [str(_SCRIPTS / "ingest_source_parquet.py"), "ingest"])
    _run_step("Rebuild scan cache", [str(_SCRIPTS / "rebuild_prescan_bulk.py")])
    _run_step("Rebuild analyses + indexes + scores", [str(_SCRIPTS / "precompute_analyses.py")])

    upload_keys = [a["key"] for a in ARTIFACTS if a["syncable"] and a["key"] != "deactivations"]
    if source_new:
        upload_keys = ["parquet", *upload_keys]
    _upload(upload_keys)

    print(f"\nRebuilt and uploaded in {(time.time() - t0)/60:.1f} min.")
    return SMART_DID_WORK


def main() -> int:
    ap = argparse.ArgumentParser(description="Medicaid Inspector data-refresh control center")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", help="show data freshness (local vs GCS)")
    sub.add_parser("smart", help="check + do only what's needed (powers the one-button update)")
    up = sub.add_parser("update", help="rebuild derived artifacts and upload to GCS")
    up.add_argument("--download", action="store_true", help="first mirror the latest parquet from GCS")
    up.add_argument("--upload-parquet", action="store_true", help="also upload the local parquet (new source data)")
    up.add_argument("--with-deactivations", action="store_true", help="also rebuild the NPPES deactivation lookup")
    up.add_argument("--yes", action="store_true", help="skip the confirmation and run the rebuild")
    args = ap.parse_args()

    if args.cmd == "update":
        return cmd_update(args)
    if args.cmd == "smart":
        return cmd_smart()
    return cmd_status()  # default


if __name__ == "__main__":
    sys.exit(main())
