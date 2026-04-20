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
    Check the CMS/HHS data catalog for a newer dataset URL.
    Uses the Socrata/DKAN metadata API to find the latest Parquet release.
    Returns a dict with status info and any new URL found.
    """
    global _dataset_info

    result = {
        "checked_at": time.time(),
        "current_url": _dataset_info["url"],
        "current_date": _dataset_info.get("detected_date") or _extract_date_from_url(_dataset_info["url"]),
        "new_url": None,
        "new_date": None,
        "update_available": False,
        "message": "",
    }

    try:
        # Try checking the Azure blob storage path pattern for newer dates
        # The URL pattern is: .../medicaid-provider-spending/{date}/medicaid-provider-spending.parquet
        base_url = "https://stopendataprod.blob.core.windows.net/datasets/medicaid-provider-spending/"

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Try to HEAD the current URL to confirm it's still valid
            try:
                resp = await client.head(settings.PARQUET_URL)
                if resp.status_code == 200:
                    result["current_url_valid"] = True
                    content_length = resp.headers.get("content-length")
                    if content_length:
                        result["current_size_bytes"] = int(content_length)
                else:
                    result["current_url_valid"] = False
            except Exception:
                result["current_url_valid"] = None

            # Try common future date patterns (monthly releases)
            current_date = _extract_date_from_url(settings.PARQUET_URL) or "2026-02-09"
            from datetime import datetime, timedelta
            try:
                cur = datetime.strptime(current_date, "%Y-%m-%d")
            except ValueError:
                cur = datetime(2026, 2, 9)

            # Check next 6 months of potential releases
            newest_found = None
            for month_offset in range(1, 7):
                check_date = cur + timedelta(days=30 * month_offset)
                candidate_date = check_date.strftime("%Y-%m-%d")
                candidate_url = f"{base_url}{candidate_date}/medicaid-provider-spending.parquet"
                try:
                    head_resp = await client.head(candidate_url)
                    if head_resp.status_code == 200:
                        newest_found = (candidate_url, candidate_date)
                except Exception:
                    continue

            if newest_found:
                result["new_url"] = newest_found[0]
                result["new_date"] = newest_found[1]
                result["update_available"] = True
                result["message"] = f"Newer dataset found: {newest_found[1]}"
            else:
                result["message"] = "No newer dataset found — current version is up to date"

    except Exception as e:
        result["message"] = f"Error checking for updates: {e}"
        _dataset_info["last_check_error"] = str(e)

    _dataset_info["last_checked"] = result["checked_at"]
    _dataset_info["detected_date"] = result.get("current_date")
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
