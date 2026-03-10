"""
Data lineage tracking — records dataset version, scan timestamps, and provider/claim
counts for each scan run. Persisted to backend/lineage.json.
"""
import json
import time
import pathlib
import threading
import logging
from typing import Optional

log = logging.getLogger(__name__)

_LINEAGE_FILE = pathlib.Path(__file__).parent.parent / "lineage.json"

_entries: list[dict] = []
_next_id: int = 1
_lock = threading.Lock()


def load_lineage_from_disk() -> None:
    """Load lineage history from disk on startup."""
    global _entries, _next_id
    try:
        if not _LINEAGE_FILE.exists():
            return
        raw = json.loads(_LINEAGE_FILE.read_text(encoding="utf-8"))
        _entries = raw.get("entries", [])
        if _entries:
            _next_id = max(e.get("id", 0) for e in _entries) + 1
        log.info("[lineage] Loaded %d lineage entries from disk", len(_entries))
    except Exception as e:
        log.warning("[lineage] Could not load lineage: %s", e)


def _save_to_disk() -> None:
    try:
        _LINEAGE_FILE.write_text(
            json.dumps({"entries": _entries}, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("[lineage] Could not save lineage: %s", e)


def record_scan_run(
    dataset_url: str,
    dataset_date: Optional[str],
    provider_count: int,
    total_claims: int,
    scan_type: str = "batch",
    duration_sec: Optional[float] = None,
    state_filter: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    """
    Record a completed scan run in the lineage log.
    Called at the end of each scan batch/smart scan/rescore.
    Returns the new entry.
    """
    global _next_id
    with _lock:
        entry = {
            "id": _next_id,
            "timestamp": time.time(),
            "dataset_url": dataset_url,
            "dataset_date": dataset_date,
            "scan_type": scan_type,
            "provider_count": provider_count,
            "total_claims": total_claims,
            "duration_sec": duration_sec,
            "state_filter": state_filter,
            "details": details,
        }
        _entries.append(entry)
        _next_id += 1
        _save_to_disk()
    log.info(
        "[lineage] Recorded scan run #%d: type=%s, providers=%d, claims=%d",
        entry["id"], scan_type, provider_count, total_claims,
    )
    return entry


def get_lineage(page: int = 1, limit: int = 50) -> dict:
    """Return paginated lineage entries (newest first)."""
    items = sorted(_entries, key=lambda e: e["timestamp"], reverse=True)
    total = len(items)
    start = (page - 1) * limit
    page_items = items[start: start + limit]

    # Compute summary stats
    dataset_versions = set()
    total_scans = total
    for e in _entries:
        url = e.get("dataset_url", "")
        date = e.get("dataset_date", "")
        if date:
            dataset_versions.add(date)
        elif url:
            dataset_versions.add(url[-30:])  # last 30 chars as fallback

    return {
        "entries": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "summary": {
            "total_scans": total_scans,
            "dataset_versions_seen": len(dataset_versions),
            "latest_scan": items[0]["timestamp"] if items else None,
            "earliest_scan": items[-1]["timestamp"] if items else None,
        },
    }


def get_latest_entry() -> Optional[dict]:
    """Return the most recent lineage entry, or None if empty."""
    if not _entries:
        return None
    return max(_entries, key=lambda e: e["timestamp"])
