"""
HIPAA PHI Access Logger.
Dedicated append-only log for all access to Protected Health Information.
Separate from the general audit log per HIPAA safeguard requirements.
Persisted to backend/phi_access_log.json.
"""
import json
import time
import pathlib
import threading
from typing import Optional

_LOG_FILE = pathlib.Path(__file__).parent.parent / "phi_access_log.json"

_entries: list[dict] = []
_next_id: int = 1
_lock = threading.Lock()

RESOURCE_TYPES = {"provider", "beneficiary", "claim", "evidence", "referral"}

PHI_PATH_PATTERNS = [
    "/api/providers/",
    "/api/beneficiary/",
    "/api/cases/",
    "/api/review/",
    "/api/referrals/",
    "/api/network/",
]


# ── disk persistence ──────────────────────────────────────────────────────────

def load_phi_log_from_disk() -> None:
    global _entries, _next_id
    try:
        if not _LOG_FILE.exists():
            return
        raw = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
        _entries = raw.get("entries", [])
        if _entries:
            _next_id = max(e.get("id", 0) for e in _entries) + 1
        print(f"[phi_logger] Loaded {len(_entries)} PHI access entries from disk")
    except Exception as e:
        print(f"[phi_logger] Could not load PHI log: {e}")


def _save_to_disk() -> None:
    try:
        _LOG_FILE.write_text(
            json.dumps({"entries": _entries}, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[phi_logger] Could not save PHI log: {e}")


# ── core logging function ─────────────────────────────────────────────────────

def log_phi_access(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    """Record a PHI access event. Returns the new entry."""
    global _next_id
    with _lock:
        entry = {
            "id": _next_id,
            "timestamp": time.time(),
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "ip_address": ip_address,
            "details": details,
        }
        _entries.append(entry)
        _next_id += 1
        _save_to_disk()
    return entry


# ── queries ───────────────────────────────────────────────────────────────────

def get_phi_log(
    filters: Optional[dict] = None,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """Return paginated PHI access log entries (newest first)."""
    items = list(_entries)

    if filters:
        if filters.get("user_id"):
            items = [e for e in items if e["user_id"] == filters["user_id"]]
        if filters.get("resource_type"):
            items = [e for e in items if e["resource_type"] == filters["resource_type"]]
        if filters.get("resource_id"):
            items = [e for e in items if e["resource_id"] == filters["resource_id"]]
        if filters.get("action"):
            items = [e for e in items if e["action"] == filters["action"]]
        if filters.get("date_from"):
            items = [e for e in items if e["timestamp"] >= filters["date_from"]]
        if filters.get("date_to"):
            items = [e for e in items if e["timestamp"] <= filters["date_to"]]

    items.sort(key=lambda x: x["timestamp"], reverse=True)
    total = len(items)
    start = (page - 1) * limit
    page_items = items[start: start + limit]
    return {"entries": page_items, "total": total, "page": page, "limit": limit}


def get_phi_log_stats() -> dict:
    """Return PHI access statistics."""
    from collections import Counter
    from datetime import datetime

    by_resource = Counter(e["resource_type"] for e in _entries)
    by_user = Counter(e["user_id"] for e in _entries)
    by_action = Counter(e["action"] for e in _entries)

    per_day: dict[str, int] = Counter()
    for e in _entries:
        day = datetime.fromtimestamp(e["timestamp"]).strftime("%Y-%m-%d")
        per_day[day] += 1

    return {
        "total_entries": len(_entries),
        "by_resource_type": dict(by_resource),
        "by_user": dict(by_user.most_common(20)),
        "by_action": dict(by_action),
        "accesses_per_day": [
            {"date": d, "count": c}
            for d, c in sorted(per_day.items())
        ],
        "oldest_entry": _entries[0]["timestamp"] if _entries else None,
        "newest_entry": _entries[-1]["timestamp"] if _entries else None,
    }


def get_phi_entry_count() -> int:
    return len(_entries)


def get_oldest_phi_timestamp() -> Optional[float]:
    return _entries[0]["timestamp"] if _entries else None


def purge_before(cutoff_ts: float) -> int:
    """Remove entries older than cutoff. Returns count removed."""
    global _entries
    with _lock:
        before = len(_entries)
        _entries = [e for e in _entries if e["timestamp"] >= cutoff_ts]
        removed = before - len(_entries)
        if removed:
            _save_to_disk()
        return removed
