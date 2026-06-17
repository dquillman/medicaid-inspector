"""
Auto-detect updated Parquet datasets from CMS/HHS data catalog.
Stores current dataset metadata in a config JSON file and provides
endpoints for checking and refreshing to newer dataset versions.
"""
import json
import time
import pathlib
import logging
import re
from typing import Optional

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_CONFIG_FILE = pathlib.Path(__file__).parent.parent / "dataset_config.json"

# In-memory state
_dataset_info: dict = {
    "url": settings.PARQUET_URL,
    "detected_date": None,
    "row_count": None,
    "last_checked": None,
    "last_check_error": None,
}


def load_dataset_config() -> None:
    """Load dataset config from disk on startup."""
    global _dataset_info
    try:
        if _CONFIG_FILE.exists():
            raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            _dataset_info.update(raw)
            log.info("[data_discovery] Loaded dataset config: url=%s", _dataset_info.get("url"))
    except Exception as e:
        log.warning("[data_discovery] Could not load dataset config: %s", e)


def _save_config() -> None:
    try:
        _CONFIG_FILE.write_text(
            json.dumps(_dataset_info, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("[data_discovery] Could not save dataset config: %s", e)


def get_dataset_info() -> dict:
    """Return current dataset metadata."""
    from data.duckdb_client import get_parquet_path, is_local
    info = dict(_dataset_info)
    info["active_path"] = get_parquet_path()
    info["is_local"] = is_local()
    info["configured_url"] = settings.PARQUET_URL
    return info


def _extract_date_from_url(url: str) -> Optional[str]:
    """Try to extract a date component from a URL like .../2026-02-09/..."""
    match = re.search(r'(\d{4}-\d{2}-\d{2})', url)
    return match.group(1) if match else None


async def check_for_updates() -> dict:
    """
    Compare the local Parquet file (if any) against the configured remote URL.

    Issues a single HEAD against PARQUET_URL and returns whether the remote
    Last-Modified is newer than the local file's mtime. Replaces the older
    Azure month-walk that probed dead URLs.
    """
    global _dataset_info
    from email.utils import parsedate_to_datetime
    from data.duckdb_client import is_local, get_local_path

    result = {
        "checked_at": time.time(),
        "current_url": settings.PARQUET_URL,
        "remote_size_bytes": None,
        "remote_last_modified": None,
        "remote_mtime": None,
        "local_size_bytes": None,
        "local_mtime": None,
        "update_available": False,
        "message": "",
    }

    if is_local():
        try:
            st = get_local_path().stat()
            result["local_size_bytes"] = st.st_size
            result["local_mtime"] = st.st_mtime
        except OSError:
            pass

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.head(settings.PARQUET_URL, follow_redirects=True)
            resp.raise_for_status()
            cl = resp.headers.get("content-length")
            lm = resp.headers.get("last-modified")
            if cl:
                result["remote_size_bytes"] = int(cl)
            if lm:
                result["remote_last_modified"] = lm
                try:
                    result["remote_mtime"] = parsedate_to_datetime(lm).timestamp()
                except Exception:
                    pass

        # Reference time = when we last *processed* the data. Locally that's the
        # parquet's mtime. When serving straight from the remote URL there's no
        # local file, so use the derived-data build time (precompute) as the
        # proxy — only then does "remote is newer" honestly mean a rebuild would
        # pick up new data. (Previously this branch blindly returned True whenever
        # we weren't local, which made prod ALWAYS claim a newer dataset existed.)
        ref_mtime = result["local_mtime"]
        if ref_mtime is None:
            try:
                from services.precomputed_store import get_generated_at
                from datetime import datetime
                ga = get_generated_at()
                if ga:
                    ref_mtime = datetime.fromisoformat(ga.replace("Z", "+00:00")).timestamp()
            except Exception:
                ref_mtime = None
        result["reference_mtime"] = ref_mtime

        if result["remote_mtime"] and ref_mtime:
            # 60s slack to ignore clock-skew false positives
            result["update_available"] = result["remote_mtime"] > ref_mtime + 60
        elif result["remote_size_bytes"] and result["local_size_bytes"]:
            result["update_available"] = result["remote_size_bytes"] != result["local_size_bytes"]
        else:
            # Not enough signal to tell — don't cry wolf.
            result["update_available"] = False

        if result["update_available"]:
            result["message"] = "Newer dataset available at the configured remote URL"
        else:
            result["message"] = "Local dataset is up to date"
    except Exception as e:
        result["message"] = f"Error checking for updates: {e}"
        _dataset_info["last_check_error"] = str(e)

    _dataset_info["last_checked"] = result["checked_at"]
    _save_config()
    return result


def switch_dataset(new_url: str) -> dict:
    """
    Switch the active dataset URL. This updates the in-memory config
    and persists it. The caller should invalidate caches and restart scans.
    """
    global _dataset_info

    old_url = _dataset_info["url"]
    _dataset_info["url"] = new_url
    _dataset_info["detected_date"] = _extract_date_from_url(new_url)
    _dataset_info["switched_at"] = time.time()
    _dataset_info["previous_url"] = old_url
    _dataset_info["row_count"] = None  # will be re-counted on next scan
    _save_config()

    log.info("[data_discovery] Switched dataset: %s -> %s", old_url, new_url)

    return {
        "switched": True,
        "old_url": old_url,
        "new_url": new_url,
        "new_date": _dataset_info["detected_date"],
        "message": "Dataset URL updated. Run a new scan to use the updated data.",
    }


async def count_dataset_rows() -> int:
    """Count total rows in the active dataset (runs a DuckDB query)."""
    from data.duckdb_client import query_async, get_parquet_path
    try:
        rows = await query_async(
            f"SELECT COUNT(*) AS cnt FROM read_parquet('{get_parquet_path()}')"
        )
        count = int(rows[0]["cnt"]) if rows else 0
        _dataset_info["row_count"] = count
        _save_config()
        return count
    except Exception as e:
        log.error("[data_discovery] Could not count rows: %s", e)
        return 0
