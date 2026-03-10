"""
Persistent storage for provider watchlist.
Disk file: backend/watchlist.json
"""
import json
import time
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

_WATCHLIST_FILE = pathlib.Path(__file__).parent.parent / "watchlist.json"

# In-memory store: NPI -> entry dict
_watchlist_items: dict[str, dict] = {}


# ── disk persistence ──────────────────────────────────────────────────────────

def load_watchlist_from_disk() -> None:
    global _watchlist_items
    try:
        if not _WATCHLIST_FILE.exists():
            return
        raw = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        _watchlist_items = {item["npi"]: item for item in raw.get("items", [])}
        print(f"[watchlist_store] Loaded {len(_watchlist_items)} watchlist items from disk")
    except Exception as e:
        print(f"[watchlist_store] Could not load watchlist: {e}")


def save_watchlist_to_disk() -> None:
    try:
        atomic_write_json(_WATCHLIST_FILE, {"items": list(_watchlist_items.values())})
    except Exception as e:
        print(f"[watchlist_store] Could not save watchlist: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

def add_to_watchlist(
    npi: str,
    name: str = "",
    specialty: str = "",
    reason: str = "",
    alert_threshold: float = 50.0,
    notes: str = "",
) -> Optional[dict]:
    """Add a provider to the watchlist. Returns the entry or None if already present."""
    if npi in _watchlist_items:
        return None
    now = time.time()
    entry = {
        "npi": npi,
        "name": name,
        "specialty": specialty,
        "added_date": now,
        "reason": reason,
        "alert_threshold": alert_threshold,
        "notes": notes,
        "active": True,
    }
    _watchlist_items[npi] = entry
    save_watchlist_to_disk()
    return entry


def remove_from_watchlist(npi: str) -> bool:
    """Remove a provider from the watchlist. Returns True if removed."""
    if npi not in _watchlist_items:
        return False
    del _watchlist_items[npi]
    save_watchlist_to_disk()
    return True


def update_entry(
    npi: str,
    notes: Optional[str] = None,
    alert_threshold: Optional[float] = None,
    active: Optional[bool] = None,
    reason: Optional[str] = None,
) -> Optional[dict]:
    """Update fields on a watchlist entry. Returns updated entry or None."""
    entry = _watchlist_items.get(npi)
    if entry is None:
        return None
    if notes is not None:
        entry["notes"] = notes
    if alert_threshold is not None:
        entry["alert_threshold"] = alert_threshold
    if active is not None:
        entry["active"] = active
    if reason is not None:
        entry["reason"] = reason
    save_watchlist_to_disk()
    return entry


# ── queries ───────────────────────────────────────────────────────────────────

def get_watchlist() -> list[dict]:
    """Return all watchlist items sorted by added_date DESC."""
    items = list(_watchlist_items.values())
    items.sort(key=lambda x: x.get("added_date", 0), reverse=True)
    return items


def get_watchlist_item(npi: str) -> Optional[dict]:
    """Return a single watchlist entry by NPI, or None."""
    return _watchlist_items.get(npi)


def is_watched(npi: str) -> bool:
    """Check if an NPI is on the watchlist."""
    return npi in _watchlist_items
