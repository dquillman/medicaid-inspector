"""
Persistent storage for provider watchlist.
Disk file: backend/watchlist.json
Primary store: Firestore (with JSON fallback during migration)
"""
import json
import logging
import time
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

logger = logging.getLogger(__name__)

_WATCHLIST_FILE = pathlib.Path(__file__).parent.parent / "watchlist.json"

# In-memory store: NPI -> entry dict
_watchlist_items: dict[str, dict] = {}


# ── persistence (Firestore primary, JSON fallback) ───────────────────────────

def _save_entry_to_firestore(entry: dict) -> None:
    """Best-effort write of a single watchlist entry to Firestore."""
    try:
        from core.firestore_store import save_watchlist_entry
        save_watchlist_entry(entry)
    except Exception as e:
        logger.warning(f"[watchlist_store] Firestore write failed (non-fatal): {e}")


def _delete_entry_from_firestore(npi: str) -> None:
    """Best-effort delete of a watchlist entry from Firestore."""
    try:
        from core.firestore_store import delete_watchlist_entry
        delete_watchlist_entry(npi)
    except Exception as e:
        logger.warning(f"[watchlist_store] Firestore delete failed (non-fatal): {e}")


def load_watchlist_from_disk() -> None:
    """Load watchlist — try Firestore first, fall back to JSON file."""
    global _watchlist_items

    # Try Firestore first
    try:
        from core.firestore_store import load_watchlist
        fs_items = load_watchlist()
        if fs_items:
            _watchlist_items = {item.get("npi", item.get("id")): item for item in fs_items}
            print(f"[watchlist_store] Loaded {len(_watchlist_items)} watchlist items from Firestore")
            return
    except Exception as e:
        logger.warning(f"[watchlist_store] Firestore load failed, falling back to JSON: {e}")

    # Fallback: load from JSON file
    try:
        if not _WATCHLIST_FILE.exists():
            return
        raw = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        _watchlist_items = {item["npi"]: item for item in raw.get("items", [])}
        print(f"[watchlist_store] Loaded {len(_watchlist_items)} watchlist items from disk")
    except Exception as e:
        print(f"[watchlist_store] Could not load watchlist: {e}")


def save_watchlist_to_disk() -> None:
    """Save to JSON file (fallback persistence)."""
    try:
        atomic_write_json(_WATCHLIST_FILE, {"items": list(_watchlist_items.values())})
    except Exception as e:
        print(f"[watchlist_store] Could not save watchlist to disk: {e}")


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
    _save_entry_to_firestore(entry)
    return entry


def remove_from_watchlist(npi: str) -> bool:
    """Remove a provider from the watchlist. Returns True if removed."""
    if npi not in _watchlist_items:
        return False
    del _watchlist_items[npi]
    save_watchlist_to_disk()
    _delete_entry_from_firestore(npi)
    return True


def update_entry(
    npi: str,
    notes: Optional[str] = None,
    alert_threshold: Optional[float] = None,
    active: Optional[bool] = None,
    reason: Optional[str] = None,
    reviewing: Optional[bool] = None,
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
    if reviewing is not None:
        entry["reviewing"] = reviewing
    save_watchlist_to_disk()
    _save_entry_to_firestore(entry)
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
