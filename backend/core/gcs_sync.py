"""
GCS persistence layer for Cloud Run.

Syncs critical data files to/from a GCS bucket so scan results,
user accounts, and app state survive deploys and cold starts.

On startup: download files from GCS -> local disk
After mutations: upload changed files to GCS (debounced)
"""
import asyncio
from contextlib import closing
from contextvars import ContextVar
import logging
import os
import pathlib
import sqlite3
import tempfile
import threading
import time

log = logging.getLogger(__name__)

_BUCKET_NAME = os.environ.get("GCS_BUCKET", "medicaid-inspector-data")
_BACKEND_DIR = pathlib.Path(__file__).parent.parent

# Files to sync — relative to backend/
_SYNC_FILES = [
    # NOTE: prescan_cache.json is NOT here — it's 1.5GB and OOMs the container
    # prescan_slim.json (54MB) is synced separately below
    "app.db",
    "users.json",
    "sessions.json",
    "review_queue.json",
    "alert_rules.json",
    "audit_log.json",
    "score_history.json",
    "watchlist.json",
    "prescan_slim.json",  # 54MB slim index — safe to load at startup
    "precomputed_analyses.json",  # workstation-precomputed heavy analyses (few MB)
    "hcpcs_index.parquet",        # code-sorted (npi, code, paid, claims) index for per-code search
    "network_index.parquet",      # NPI-sorted ego-network index for instant /api/network/{npi}
    "roi_data.json",
    "supervised_model.json",  # trained supervised-ML metrics + per-NPI predictions
    "ml_scores.json",         # Isolation Forest anomaly scores
    "npi_deactivations.json", # deactivated-NPI lookup (dead_npi_billing signal)
    "npi_deactivation_windows.json",  # deactivated-then-reactivated NPIs {npi: [deact, react]}
    "perse_leads.json",       # per-se sweep over ALL 617k billing NPIs, not just the scanned 106k
    "missing_npis.json",      # rank-gap + per-se NPIs the "Add missing" button scans (built offline)
    "notifications.json",
    "saved_searches.json",
    "referrals.json",
    "oig_tips.json",          # HHS-OIG Hotline tip log
    "evidence_metadata.json",
    "lineage.json",
    "hal_bugs.json",          # bugs logged via HAL's log_bug tool (durable on Cloud Run)
    "auto_prep_state.json",   # nightly case-prep: last run date + prepared NPI (one/day)
    "feedback_data.json",     # signal FP/TP counts + learned weight multipliers
]

_client = None
_bucket = None
_upload_lock = threading.Lock()
_last_upload: dict[str, float] = {}
_pending_timers: dict[str, "threading.Timer"] = {}  # trailing-edge debounce
_sync_lock = threading.RLock()
_generations: dict[str, int] = {}
_sync_status: dict[str, dict] = {}
# Mutable request-owned event list propagates through asyncio.to_thread and
# AnyIO threadpools; unrelated threads/tasks have no collection by default.
_request_persistence_events: ContextVar[list[dict] | None] = ContextVar("mfi_persistence_events", default=None)


def begin_request_persistence():
    events: list[dict] = []
    return _request_persistence_events.set(events), events


def end_request_persistence(token) -> None:
    _request_persistence_events.reset(token)



def _set_status(name: str, state: str, error: str = "", *, request_write: bool = True) -> None:
    with _sync_lock:
        _sync_status[name] = {"state": state, "updated_at": time.time(), "error": error,
                              "durable": state == "synced", "generation": _generations.get(name)}
        events = _request_persistence_events.get()
        if request_write and events is not None:
            events.append({"object": name, "state": state})


def get_sync_status() -> dict:
    """Admin diagnostics contain only metadata, never state-file contents."""
    with _sync_lock:
        return {"storage_model": "whole-file optimistic concurrency; single instance required",
                "objects": {name: dict(value) for name, value in _sync_status.items()},
                "pending_count": sum(value["state"] == "pending" for value in _sync_status.values()),
                "error_count": sum(value["state"] in ("conflict", "error", "unavailable", "untracked") for value in _sync_status.values())}


_DEBOUNCE_SEC = 5  # min seconds between uploads of the same file


def _get_bucket():
    """Lazy-init the GCS client and bucket."""
    global _client, _bucket
    if not _BUCKET_NAME:
        return None
    # The aggregate-only public bucket must never receive cases, sessions,
    # evidence, credentials, or state snapshots, even through a stale client.
    if _BUCKET_NAME == "medicaid-inspector-public-aggregates":
        log.error("Refusing public aggregate bucket as operational storage")
        return None
    if _bucket is not None:
        return _bucket
    try:
        from google.cloud import storage
        _client = storage.Client()
        _bucket = _client.bucket(_BUCKET_NAME)
        log.info("[gcs_sync] Connected to bucket: %s", _BUCKET_NAME)
        return _bucket
    except Exception as e:
        log.warning("[gcs_sync] GCS not available (running locally?): %s", e)
        return None


_PARQUET_BLOB = "medicaid-provider-spending.parquet"
_PARQUET_LOCAL = _BACKEND_DIR / "data" / "medicaid-provider-spending.parquet"


_SHRINK_GUARD_RATIO = 0.5  # refuse to overwrite a local file if GCS blob is <50% its size
_SHRINK_GUARD_MIN_LOCAL_BYTES = 1_000_000  # only guard files larger than 1MB locally


def download_state_files() -> int:
    """Download small state files from GCS (fast, safe for startup). Skips Parquet.

    Includes a size guard: if a non-trivial local file (>1MB) already exists and
    the GCS blob is suspiciously smaller (<50% of local size), we skip the
    overwrite and log a warning. This prevents a stale or empty GCS object from
    clobbering the larger copy baked into the Docker image (the failure mode
    that left the slim prescan cache empty on prod).
    """
    bucket = _get_bucket()
    if not bucket:
        _set_status("startup", "unavailable", "State storage unavailable; local files have no remote durability acknowledgement", request_write=False)
        return 0

    downloaded = 0
    for filename in _SYNC_FILES:
        local_path = _BACKEND_DIR / filename
        blob = bucket.blob(filename)
        try:
            if not blob.exists():
                _generations[filename] = 0
                _set_status(filename, "absent", request_write=False)
                continue
            # Size guard — fetch blob metadata so we can compare before downloading
            blob.reload()
            blob_size = blob.size or 0
            local_size = local_path.stat().st_size if local_path.exists() else 0
            if (
                local_size > _SHRINK_GUARD_MIN_LOCAL_BYTES
                and blob_size < local_size * _SHRINK_GUARD_RATIO
            ):
                _generations.pop(filename, None)
                _set_status(filename, "untracked", "Remote size guard rejected download; reconcile before upload", request_write=False)
                log.warning(
                    "[gcs_sync] Refusing to overwrite %s — local=%.1fMB but GCS blob=%.1fMB (<%.0f%%). "
                    "Keeping the larger local copy.",
                    filename,
                    local_size / (1024 * 1024),
                    blob_size / (1024 * 1024),
                    _SHRINK_GUARD_RATIO * 100,
                )
                continue
            generation = int(blob.generation)
            fd, downloaded_path = tempfile.mkstemp(dir=str(local_path.parent), suffix=".download")
            os.close(fd)
            try:
                blob.download_to_filename(downloaded_path, if_generation_match=generation)
                os.replace(downloaded_path, local_path)
            finally:
                pathlib.Path(downloaded_path).unlink(missing_ok=True)
            _generations[filename] = generation
            _set_status(filename, "synced", request_write=False)
            size_kb = local_path.stat().st_size / 1024
            log.info("[gcs_sync] Downloaded %s (%.1f KB)", filename, size_kb)
            downloaded += 1
        except Exception as e:
            _generations.pop(filename, None)
            _set_status(filename, "error", "State download failed; remote generation not adopted", request_write=False)
            log.warning("[gcs_sync] Failed to download %s: %s", filename, e)

    return downloaded


def download_parquet() -> bool:
    """Download the Parquet dataset from GCS. Called in background after server starts."""
    if _PARQUET_LOCAL.exists() and _PARQUET_LOCAL.stat().st_size > 1_000_000:
        log.info("[gcs_sync] Parquet already on disk (%.0f MB)", _PARQUET_LOCAL.stat().st_size / (1024 * 1024))
        return True

    bucket = _get_bucket()
    if not bucket:
        return False

    blob = bucket.blob(_PARQUET_BLOB)
    try:
        if not blob.exists():
            log.info("[gcs_sync] No Parquet in GCS bucket — will use remote URL")
            return False
        _PARQUET_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        log.info("[gcs_sync] Downloading Parquet dataset from GCS (this may take a minute)...")
        blob.download_to_filename(str(_PARQUET_LOCAL))
        size_mb = _PARQUET_LOCAL.stat().st_size / (1024 * 1024)
        log.info("[gcs_sync] Parquet dataset ready (%.0f MB) — scans will use local data", size_mb)
        return True
    except Exception as e:
        log.warning("[gcs_sync] Failed to download Parquet: %s", e)
        return False


async def download_parquet_async() -> bool:
    """Async wrapper for background Parquet download."""
    return await asyncio.to_thread(download_parquet)


def download_prescan_cache() -> bool:
    """Download prescan_cache.json from GCS. Called in background — it's 1.5GB."""
    local_path = _BACKEND_DIR / "prescan_cache.json"
    bucket = _get_bucket()
    if not bucket:
        return False
    blob = bucket.blob("prescan_cache.json")
    try:
        if not blob.exists():
            log.info("[gcs_sync] No prescan_cache.json in GCS bucket")
            return False
        log.info("[gcs_sync] Downloading prescan_cache.json from GCS (large file)...")
        blob.download_to_filename(str(local_path))
        size_mb = local_path.stat().st_size / (1024 * 1024)
        log.info("[gcs_sync] prescan_cache.json ready (%.0f MB)", size_mb)
        return True
    except Exception as e:
        log.warning("[gcs_sync] Failed to download prescan_cache.json: %s", e)
        return False


async def download_prescan_cache_async() -> bool:
    """Async wrapper for background prescan cache download."""
    return await asyncio.to_thread(download_prescan_cache)


def download_all() -> int:
    """Download everything (state files + Parquet). Used for manual sync."""
    count = download_state_files()
    if download_parquet():
        count += 1
    return count


def _conditional_upload(object_path: str, uploader) -> bool:
    """Refuse stale or unloaded whole-file overwrites, including metadata."""
    with _sync_lock:
        bucket = _get_bucket()
        if not bucket:
            _set_status(object_path, "unavailable", "Object storage unavailable")
            return False
        try:
            blob = bucket.blob(object_path)
            expected = _generations.get(object_path)
            if expected is None:
                if blob.exists():
                    _set_status(object_path, "untracked", "Remote object not loaded; reconcile before overwrite")
                    return False
                expected = 0
            uploader(blob, expected)
            if blob.generation is None:
                _set_status(object_path, "error", "Upload returned no generation; cannot acknowledge durability")
                return False
            _generations[object_path] = int(blob.generation)
            _set_status(object_path, "synced")
            return True
        except Exception as error:
            code = getattr(error, "code", None)
            code = code() if callable(code) else code
            conflict = code == 412 or type(error).__name__ in ("PreconditionFailed", "Conflict")
            _set_status(object_path, "conflict" if conflict else "error",
                        "Remote generation changed; reconcile before retry" if conflict else "Upload failed; local state remains unsynced")
            log.warning("[gcs_sync] Conditional upload failed for %s: %s", object_path, error)
            return False


def _do_upload_snapshot(filename: str) -> bool:
    """Upload immutable snapshot; SQLite backup includes committed WAL data."""
    local_path = (_BACKEND_DIR / filename).resolve()
    if not local_path.is_relative_to(_BACKEND_DIR.resolve()):
        raise ValueError("State path must remain within backend directory")
    if not local_path.exists():
        _set_status(filename, "error", "Local state file is missing")
        return False
    fd, snapshot_path = tempfile.mkstemp(suffix=local_path.suffix)
    os.close(fd)
    try:
        if local_path.suffix == ".db":
            with closing(sqlite3.connect(local_path.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(snapshot_path)) as destination:
                    source.backup(destination)
        else:
            import shutil
            with local_path.open("rb") as source, open(snapshot_path, "wb") as destination:
                shutil.copyfileobj(source, destination)
        return _conditional_upload(filename, lambda blob, expected: blob.upload_from_filename(snapshot_path, if_generation_match=expected))
    except Exception as error:
        _set_status(filename, "error", "Could not create consistent upload snapshot")
        log.warning("[gcs_sync] Snapshot failed for %s: %s", filename, error)
        return False
    finally:
        pathlib.Path(snapshot_path).unlink(missing_ok=True)


def _do_upload(filename: str) -> bool:
    # Serialize snapshot capture as well as upload, so an older in-process
    # snapshot cannot overtake a newer one while waiting for the upload lock.
    with _sync_lock:
        return _do_upload_snapshot(filename)


def _flush_pending(filename: str) -> None:
    """Trailing-edge upload fired by the debounce timer."""
    with _upload_lock:
        _pending_timers.pop(filename, None)
        _last_upload[filename] = time.time()
    _do_upload(filename)


def upload_file(filename: str) -> bool:
    """Upload a file to GCS, debounced with a TRAILING edge.

    The old version dropped writes: inside the debounce window it returned
    False and scheduled nothing, so the LAST write in a burst never reached GCS
    and was lost on the next restart/redeploy (audit 2026-07-25, #3). Now a
    debounced call arms a timer for the remainder of the window, so the newest
    state is always flushed. One timer per file — a burst coalesces into a
    single upload instead of being silently discarded.
    """
    with _upload_lock:
        now = time.time()
        last = _last_upload.get(filename, 0)
        elapsed = now - last
        if elapsed < _DEBOUNCE_SEC:
            if filename not in _pending_timers:
                delay = max(0.05, _DEBOUNCE_SEC - elapsed)
                t = threading.Timer(delay, _flush_pending, args=(filename,))
                t.daemon = True          # never block interpreter shutdown
                _pending_timers[filename] = t
                t.start()
            _set_status(filename, "pending", "Upload deferred; not yet durable")
            return False                 # deferred, NOT dropped
        _last_upload[filename] = now

    return _do_upload(filename)


def upload_bytes(object_path: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
    """Write raw bytes to GCS at `object_path`. Returns False if unavailable."""
    return _conditional_upload(object_path, lambda blob, expected: blob.upload_from_string(data, content_type=content_type, if_generation_match=expected))


def download_bytes(object_path: str) -> bytes | None:
    """Read an object back from GCS. None if missing/unavailable."""
    bucket = _get_bucket()
    if not bucket:
        return None
    try:
        blob = bucket.blob(object_path)
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception as e:
        log.warning("[gcs_sync] Failed to download object %s: %s", object_path, e)
        return None


def object_exists(object_path: str) -> bool:
    bucket = _get_bucket()
    if not bucket:
        return False
    try:
        return bucket.blob(object_path).exists()
    except Exception:
        return False


def upload_all() -> int:
    """Upload all existing sync files to GCS. Returns count uploaded."""
    return sum(_do_upload(filename) for filename in _SYNC_FILES if (_BACKEND_DIR / filename).exists())


async def upload_file_async(filename: str) -> bool:
    """Async wrapper for upload_file."""
    return await asyncio.to_thread(upload_file, filename)


async def sync_after_scan():
    """Upload scan-related files after a scan batch completes."""
    import os as _os
    _is_cloud_run = _os.environ.get("K_SERVICE") is not None
    if _is_cloud_run:
        # Cloud Run serves the slim index. WRITE it before uploading: nothing
        # else does, so this used to upload the same file the container started
        # with and every scan result died at the next recycle (measured
        # 2026-07-27 — 11,296 scored providers lost silently).
        from core.store import save_slim_to_disk
        await asyncio.to_thread(save_slim_to_disk)
        await asyncio.to_thread(upload_file, "prescan_slim.json")
    else:
        await asyncio.to_thread(upload_file, "prescan_cache.json")
    await asyncio.to_thread(upload_file, "app.db")


async def sync_after_user_change():
    """Upload user-related files after auth changes."""
    await asyncio.to_thread(upload_file, "users.json")
    await asyncio.to_thread(upload_file, "sessions.json")
    await asyncio.to_thread(upload_file, "app.db")
