"""Guarded local-only release validation. Execute the COPIED staging script only.

Requires --stage-root, MFI_STAGING_REFRESH=1, and .mfi-release-validation.json.
Produces aggregate public results plus a private stage log; never deploys.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import traceback


def validate_stage(stage: Path) -> Path:
    stage = stage.resolve()
    if os.environ.get("MFI_STAGING_REFRESH") != "1":
        raise ValueError("Explicit staging guard environment is required")
    marker = json.loads((stage / ".mfi-release-validation.json").read_text())
    if marker.get("purpose") != "release-validation":
        raise ValueError("Invalid staging marker")
    operator = Path(marker["operator_backend"]).resolve()
    if stage == operator or not stage.is_relative_to(operator / ".tmp"):
        raise ValueError("Stage must be isolated beneath operator backend/.tmp")
    if Path(__file__).resolve().parents[1] != stage:
        raise ValueError("Execute the copied script inside the marked stage")
    if (stage / ".env").exists():
        raise ValueError("Stage must not contain operator .env credentials")
    if not (stage / "data" / "medicaid-provider-spending.parquet").is_file():
        raise ValueError("Stage local Parquet is required")
    for item in stage.rglob("*"):
        if item.is_symlink():
            raise ValueError("Stage symlinks are not permitted")
    return stage


def prepare_offline(stage):
    # All configuration is established before importing application modules.
    for key in list(os.environ):
        if any(word in key.upper() for word in ("API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "HAL_TOKEN", "SMTP_PASS")):
            os.environ.pop(key, None)
    tmp = stage / "scratch"
    tmp.mkdir(exist_ok=True)
    os.environ.update(GCS_BUCKET="", MFI_DISABLE_BACKGROUND_JOBS="1", HAL_QCODE_DIR="",
                      NARRATIVE_LLM_ENABLED="false", TEMP=str(tmp), TMP=str(tmp),
                      LOCAL_PARQUET_PATH=str(stage / "data" / "medicaid-provider-spending.parquet"))
    import tempfile
    tempfile.tempdir = str(tmp)
    import socket
    original_connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        raise OSError("Staging external networking disabled")
    socket.socket.connect = local_only
    original_connect_ex = socket.socket.connect_ex
    def local_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect_ex(sock, address)
        raise OSError("Staging external networking disabled")
    socket.socket.connect_ex = local_connect_ex
    original_lookup = socket.getaddrinfo
    def local_lookup(host, *args, **kwargs):
        if host in ("localhost", "127.0.0.1", "::1", None):
            return original_lookup(host, *args, **kwargs)
        raise OSError("Staging external name resolution disabled")
    socket.getaddrinfo = local_lookup
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(OSError("Staging external networking disabled"))
    import duckdb
    original_duckdb_connect = duckdb.connect
    def local_connect(*args, **kwargs):
        config = dict(kwargs.pop("config", {}) or {})
        config.update(autoinstall_known_extensions="false", autoload_known_extensions="false")
        return original_duckdb_connect(*args, config=config, **kwargs)
    duckdb.connect = local_connect
    from data import duckdb_client as db
    def connection():
        if not getattr(db._thread_local, "con", None):
            con = duckdb.connect(":memory:")
            con.execute("SET threads=2")
            db._thread_local.con = con
        return db._thread_local.con
    db.get_connection = connection
    from core import gcs_sync
    async def disabled_async(*args, **kwargs):
        return False
    for name in ("upload_file", "upload_bytes", "upload_all", "download_all", "download_state_files",
                 "download_prescan_cache", "download_parquet", "object_exists"):
        setattr(gcs_sync, name, lambda *a, **k: False)
    gcs_sync.download_bytes = lambda *a, **k: None
    for name in ("upload_file_async", "sync_after_scan", "sync_after_user_change", "download_prescan_cache_async", "download_parquet_async"):
        setattr(gcs_sync, name, disabled_async)
    from core.config import settings
    settings.HAL_QCODE_DIR = ""
    settings.HAL_TOKEN = ""
    settings.MMIS_API_KEY = ""
    settings.MMIS_ENDPOINT_URL = ""
    settings.LOCAL_PARQUET_PATH = str(stage / "data" / "medicaid-provider-spending.parquet")


def summarize(providers):
    flags = Counter()
    for row in providers:
        flags.update(item["signal"] for item in row.get("flags", []) if item.get("flagged"))
    scores = [float(row.get("risk_score") or 0) for row in providers]
    return {"providers": len(providers), "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
            "scores_over_10": sum(value > 10 for value in scores), "active_signals": dict(flags),
            "scoring_metadata_recorded": sum(bool(row.get("scoring_metadata")) for row in providers)}


def iter_provider_rows(path):
    """Stream a saved provider array without allocating the entire JSON document."""
    import re
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as stream:
        buffer = ""
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                raise ValueError("Provider array missing in snapshot")
            buffer += chunk
            stripped = buffer.lstrip()
            if stripped.startswith("["):
                buffer = stripped[1:]
                break
            match = re.search(r'"providers"\s*:\s*\[', buffer)
            if match:
                buffer = buffer[match.end():]
                break
            if len(buffer) > 4 * 1024 * 1024:
                raise ValueError("Snapshot provider-array header exceeds bound")
        while True:
            buffer = buffer.lstrip(" \r\n\t,")
            if buffer.startswith("]"):
                return
            try:
                row, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    raise ValueError("Truncated provider snapshot")
                buffer += chunk
                continue
            if not isinstance(row, dict):
                raise ValueError("Unexpected provider snapshot row")
            yield row
            buffer = buffer[end:]


def summarize_snapshot(path):
    flags = Counter()
    previous_scores = {}
    count = over_threshold = metadata = 0
    total_score = 0.0
    for row in iter_provider_rows(path):
        score = float(row.get("risk_score") or 0)
        previous_scores[row["npi"]] = score
        count += 1
        total_score += score
        over_threshold += score > 10
        metadata += bool(row.get("scoring_metadata"))
        flags.update(item["signal"] for item in row.get("flags", []) if item.get("flagged"))
    return {"providers": count, "mean_score": round(total_score/count, 3) if count else None,
            "scores_over_10": over_threshold, "active_signals": dict(flags),
            "scoring_metadata_recorded": metadata}, previous_scores


async def refresh(stage, public, resume_derived=False):
    from core import store, oig_store
    from services import scan_engine, risk_scorer
    from data.duckdb_client import provider_aggregate_sql, query_async
    if resume_derived:
        public("Streaming original baseline snapshot for resumed comparison")
        baseline = stage.parent / "input-snapshots" / "prescan_cache.json"
        before, previous_scores = summarize_snapshot(baseline)
    public("Loading staging cache")
    if not store.load_from_disk("prescan_cache.json"):
        raise RuntimeError("Stage full cache failed to load")
    exclusion_loaded = oig_store.load_oig_from_disk()
    if not exclusion_loaded:
        raise RuntimeError("Stage exclusion snapshot unavailable; refusing to turn missing evidence into clear results")
    providers = store.get_prescanned()
    if not resume_derived:
        before = summarize(providers)
        previous_scores = {row["npi"]: float(row.get("risk_score") or 0) for row in providers}
    elif not providers or any(not row.get("scoring_metadata") for row in providers):
        raise RuntimeError("Resume requires a fully rescored staging cache with recorded metadata")
    # Reuse existing slim enrichment; no NPPES requests or inferred new facts.
    slim_file = stage / "prescan_slim.json"
    if slim_file.exists():
        slim = json.loads(slim_file.read_text(encoding="utf-8"))
        slim_rows = slim if isinstance(slim, list) else slim.get("providers", [])
        enriched = {row["npi"]: row for row in slim_rows}
        for row in providers:
            source = enriched.get(row["npi"], {})
            for key in ("nppes", "specialty", "state", "city", "zip", "provider_name"):
                if not row.get(key) and source.get(key):
                    row[key] = source[key]
        del slim, slim_rows, enriched
    if resume_derived:
        public("Reusing saved rescored staging records; no second rescore")
        from core.config import settings
        result = {"rescored": len(providers),
                  "flagged": sum(float(row.get("risk_score") or 0) > settings.RISK_THRESHOLD for row in providers),
                  "new_review_items": None}
    else:
        public("Rescoring staging records with normal services")
        result = await scan_engine.rescore_cached_providers()
    providers = store.get_prescanned()
    after = summarize(providers)
    changed = sum(float(row.get("risk_score") or 0) != previous_scores.get(row["npi"]) for row in providers)
    ordered = sorted(providers, key=lambda row: float(row.get("risk_score") or 0))
    picks = sorted(set([0, len(ordered)//4, len(ordered)//2, 3*len(ordered)//4, len(ordered)-1])) if ordered else []
    parity = []
    public("Checking representative live versus batch parity")
    for ordinal, index in enumerate(picks, 1):
        cached = ordered[index]
        rows = await query_async(provider_aggregate_sql(where="BILLING_PROVIDER_NPI_NUM = ?", limit=None), (cached["npi"],))
        if not rows:
            parity.append({"sample": ordinal, "status": "missing_source_aggregate"})
            continue
        aggregate = {**cached, **rows[0]}
        live = await risk_scorer.score_provider(cached["npi"], aggregate)
        same_score = live["risk_score"] == cached["risk_score"]
        batch_signals = {item["signal"]: (item["score"], item["flagged"]) for item in cached.get("signal_results", [])}
        live_signals = {item["signal"]: (item["score"], item["flagged"]) for item in live.get("signal_results", [])}
        parity.append({"sample": ordinal, "score_equal": same_score, "signals_equal": live_signals == batch_signals,
                       "batch_score": cached["risk_score"], "live_score": live["risk_score"]})
    report = {"status": "derived_pending", "rescore_performed_this_run": not resume_derived, "scope": "isolated local snapshot; no external freshness or fraud accuracy claim",
              "before": before, "after": after, "changed_scores": changed,
              "exclusion_snapshot_loaded": exclusion_loaded,
              "providers_with_copied_registry_enrichment": sum(bool(row.get("nppes")) for row in providers),
              "rescore_counts": {key: result[key] for key in ("rescored", "flagged", "new_review_items")},
              "representative_parity": parity,
              "limitations": ["Five stratified records do not establish whole-dataset parity.",
                              "Copied enrichment and exclusion snapshots may be stale.",
                              "Stage review queue and derived artifacts changed; operator state untouched."]}
    (stage / "refresh-validation-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    public("Parity checkpoint saved; building staging derived analyses and indexes")
    from scripts import precompute_analyses
    if await asyncio.to_thread(precompute_analyses.main) != 0:
        raise RuntimeError("Precompute failed")
    report["status"] = "complete"
    (stage / "refresh-validation-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-root", required=True, type=Path)
    parser.add_argument("--resume-derived", action="store_true", help="Reuse already-rescored stage cache; stream original input snapshot for baseline")
    args = parser.parse_args()
    try:
        stage = validate_stage(args.stage_root)
    except Exception as error:
        print(f"Staging guard rejected: {type(error).__name__}", flush=True)
        return 1
    sys.path.insert(0, str(stage))
    os.chdir(stage)
    output = sys.stdout
    started = time.monotonic()
    def public(message):
        output.write(f"[staging {int(time.monotonic()-started)}s] {message}\n")
        output.flush()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(30):
            public("Validation still running")
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    with (stage / "refresh-private.log").open("a" if args.resume_derived else "w", encoding="utf-8") as private:
        with redirect_stdout(private), redirect_stderr(private):
            logging.basicConfig(stream=private, level=logging.WARNING, force=True)
            try:
                prepare_offline(stage)
                report = asyncio.run(refresh(stage, public, args.resume_derived))
            except BaseException as error:
                traceback.print_exc()
                public(f"Validation failed ({type(error).__name__}); details retained in private stage log")
                return 1
            finally:
                stop.set()
    public(json.dumps(report, separators=(",", ":")))
    return 0 if all(item.get("score_equal") and item.get("signals_equal") for item in report["representative_parity"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
