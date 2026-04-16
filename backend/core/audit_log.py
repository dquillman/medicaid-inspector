"""
System-wide audit log.
Persisted to backend/audit_log.json — every significant action gets recorded here.
"""
import json
import time
import pathlib
import threading
from typing import Optional

from core.safe_io import atomic_write_json

_LOG_FILE = pathlib.Path(__file__).parent.parent / "audit_log.json"

# In-memory log: list of entry dicts
_entries: list[dict] = []
_next_id: int = 1
_lock = threading.Lock()

ACTION_TYPES = {
    "scan_started", "scan_completed", "provider_viewed", "review_status_changed",
    "review_assigned", "report_exported", "alert_rule_created", "alert_evaluated",
    "exclusion_checked", "ml_model_trained", "narrative_generated", "hours_logged",
    "priority_changed", "review_bulk_updated", "review_backfilled", "scan_reset",
    "referral_submitted", "referral_updated", "evidence_uploaded", "retention_enforced",
}

ENTITY_TYPES = {"provider", "review", "alert_rule", "system", "report", "referral", "evidence"}


# ── disk persistence ──────────────────────────────────────────────────────────

def load_audit_from_disk() -> None:
    global _entries, _next_id
    try:
        if not _LOG_FILE.exists():
            return
        raw = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
        loaded = raw.get("entries", [])
        next_id = (max(e.get("id", 0) for e in loaded) + 1) if loaded else 1
        with _lock:
            _entries = loaded
            _next_id = next_id
        print(f"[audit_log] Loaded {len(_entries)} audit entries from disk")
    except Exception as e:
        print(f"[audit_log] Could not load audit log: {e}")


def _save_to_disk() -> None:
    # Takes its own snapshot — safe to call with or without _lock held.
    snapshot = list(_entries)
    try:
        atomic_write_json(_LOG_FILE, {"entries": snapshot})
    except Exception as e:
        print(f"[audit_log] Could not save audit log: {e}")


# ── core logging function ─────────────────────────────────────────────────────

def log_action(
    action_type: str,
    entity_type: str,
    entity_id: str,
    details: Optional[dict] = None,
    user: str = "system",
    ip_address: Optional[str] = None,
) -> dict:
    """Record an action in the global audit log. Returns the new entry."""
    global _next_id
    with _lock:
        entry = {
            "id": _next_id,
            "timestamp": time.time(),
            "action_type": action_type,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "user": user,
            "details": details,
            "ip_address": ip_address,
        }
        _entries.append(entry)
        _next_id += 1
        _save_to_disk()
    return entry


# ── queries ───────────────────────────────────────────────────────────────────

def get_audit_log(
    filters: Optional[dict] = None,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """
    Return paginated audit log entries (newest first).
    Optional filters: action_type, entity_type, entity_id, date_from, date_to
    """
    with _lock:
        items = list(_entries)

    if filters:
        if filters.get("action_type"):
            items = [e for e in items if e["action_type"] == filters["action_type"]]
        if filters.get("entity_type"):
            items = [e for e in items if e["entity_type"] == filters["entity_type"]]
        if filters.get("entity_id"):
            items = [e for e in items if e["entity_id"] == filters["entity_id"]]
        if filters.get("date_from"):
            items = [e for e in items if e["timestamp"] >= filters["date_from"]]
        if filters.get("date_to"):
            items = [e for e in items if e["timestamp"] <= filters["date_to"]]

    # Sort newest first
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    total = len(items)
    start = (page - 1) * limit
    page_items = items[start: start + limit]
    return {"entries": page_items, "total": total, "page": page, "limit": limit}


def get_entity_history(entity_type: str, entity_id: str) -> list:
    """Return all audit entries for a specific entity, newest first."""
    with _lock:
        snapshot = list(_entries)
    items = [
        e for e in snapshot
        if e["entity_type"] == entity_type and e["entity_id"] == str(entity_id)
    ]
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items


def purge_entries_before(cutoff_ts: float) -> int:
    """Remove all audit entries older than cutoff_ts (Unix timestamp). Returns count removed."""
    global _entries
    with _lock:
        before = len(_entries)
        _entries = [e for e in _entries if e["timestamp"] >= cutoff_ts]
        removed = before - len(_entries)
        if removed:
            _save_to_disk()
    return removed


def get_audit_stats() -> dict:
    """Return audit statistics: counts by action type, per-day counts, most active entities."""
    from collections import Counter
    from datetime import datetime

    with _lock:
        snapshot = list(_entries)

    by_action = Counter(e["action_type"] for e in snapshot)
    by_day: dict[str, int] = Counter()
    entity_counter: Counter = Counter()

    for e in snapshot:
        day = datetime.fromtimestamp(e["timestamp"]).strftime("%Y-%m-%d")
        by_day[day] += 1
        entity_counter[f"{e['entity_type']}:{e['entity_id']}"] += 1

    # Top 10 most active entities
    most_active = [
        {"entity": k, "count": v}
        for k, v in entity_counter.most_common(10)
    ]

    # Per-day sorted by date
    actions_per_day = [
        {"date": d, "count": c}
        for d, c in sorted(by_day.items())
    ]

    return {
        "total_entries": len(snapshot),
        "by_action_type": dict(by_action),
        "actions_per_day": actions_per_day,
        "most_active_entities": most_active,
    }
