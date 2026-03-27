"""
GCS persistence layer for Cloud Run.

Syncs critical data files to/from a GCS bucket so scan results,
user accounts, and app state survive deploys and cold starts.

On startup: download files from GCS -> local disk
After mutations: upload changed files to GCS (debounced)
"""
import asyncio
import logging
import os
import pathlib
import threading
import time

log = logging.getLogger(__name__)

_BUCKET_NAME = os.environ.get("GCS_BUCKET", "medicaid-inspector-data")
_BACKEND_DIR = pathlib.Path(__file__).parent.parent

# Files to sync — relative to backend/
_SYNC_FILES = [
    "prescan_cache.json",
    "app.db",
    "users.json",
    "sessions.json",
    "review_queue.json",
    "alert_rules.json",
    "audit_log.json",
    "score_history.json",
    "watchlist.json",
]

_client = None
_bucket = None
_upload_lock = threading.Lock()
_last_upload: dict[str, float] = {}
_DEBOUNCE_SEC = 5  # min seconds between uploads of the same file


def _get_bucket():
    """Lazy-init the GCS client and bucket."""
    global _client, _bucket
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


def download_all() -> int:
    """Download all sync files from GCS to local disk. Returns count downloaded."""
    bucket = _get_bucket()
    if not bucket:
        return 0

    downloaded = 0
    for filename in _SYNC_FILES:
        local_path = _BACKEND_DIR / filename
        blob = bucket.blob(filename)
        try:
            if blob.exists():
                blob.download_to_filename(str(local_path))
                size_kb = local_path.stat().st_size / 1024
                log.info("[gcs_sync] Downloaded %s (%.1f KB)", filename, size_kb)
                downloaded += 1
        except Exception as e:
            log.warning("[gcs_sync] Failed to download %s: %s", filename, e)

    return downloaded


def upload_file(filename: str) -> bool:
    """Upload a single file to GCS. Debounced to avoid excessive writes."""
    with _upload_lock:
        now = time.time()
        last = _last_upload.get(filename, 0)
        if now - last < _DEBOUNCE_SEC:
            return False
        _last_upload[filename] = now

    bucket = _get_bucket()
    if not bucket:
        return False

    local_path = _BACKEND_DIR / filename
    if not local_path.exists():
        return False

    try:
        blob = bucket.blob(filename)
        blob.upload_from_filename(str(local_path))
        size_kb = local_path.stat().st_size / 1024
        log.info("[gcs_sync] Uploaded %s (%.1f KB)", filename, size_kb)
        return True
    except Exception as e:
        log.warning("[gcs_sync] Failed to upload %s: %s", filename, e)
        return False


def upload_all() -> int:
    """Upload all existing sync files to GCS. Returns count uploaded."""
    bucket = _get_bucket()
    if not bucket:
        return 0

    uploaded = 0
    for filename in _SYNC_FILES:
        local_path = _BACKEND_DIR / filename
        if local_path.exists():
            try:
                blob = bucket.blob(filename)
                blob.upload_from_filename(str(local_path))
                size_kb = local_path.stat().st_size / 1024
                log.info("[gcs_sync] Uploaded %s (%.1f KB)", filename, size_kb)
                uploaded += 1
            except Exception as e:
                log.warning("[gcs_sync] Failed to upload %s: %s", filename, e)
    return uploaded


async def upload_file_async(filename: str) -> bool:
    """Async wrapper for upload_file."""
    return await asyncio.to_thread(upload_file, filename)


async def sync_after_scan():
    """Upload scan-related files after a scan batch completes."""
    await asyncio.to_thread(upload_file, "prescan_cache.json")
    await asyncio.to_thread(upload_file, "app.db")


async def sync_after_user_change():
    """Upload user-related files after auth changes."""
    await asyncio.to_thread(upload_file, "users.json")
    await asyncio.to_thread(upload_file, "sessions.json")
    await asyncio.to_thread(upload_file, "app.db")
