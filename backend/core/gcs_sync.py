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


_PARQUET_BLOB = "medicaid-provider-spending.parquet"
_PARQUET_LOCAL = _BACKEND_DIR / "data" / "medicaid-provider-spending.parquet"


def download_state_files() -> int:
    """Download small state files from GCS (fast, safe for startup). Skips Parquet."""
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
