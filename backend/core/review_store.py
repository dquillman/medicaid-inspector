"""
Persistent storage for flagged provider review cases.
Disk file: backend/review_queue.json
"""
import json
import time
import pathlib
from typing import Optional

_QUEUE_FILE = pathlib.Path(__file__).parent.parent / "review_queue.json"

# In-memory store: NPI -> item dict
_review_items: dict[str, dict] = {}

VALID_STATUSES = {"pending", "assigned", "investigating", "confirmed_fraud", "referred", "dismissed"}


# ── disk persistence ──────────────────────────────────────────────────────────

def load_review_from_disk() -> None:
    global _review_items
    try:
        if not _QUEUE_FILE.exists():
            return
        raw = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
        _review_items = {item["npi"]: item for item in raw.get("items", [])}
        print(f"[review_store] Loaded {len(_review_items)} review items from disk")
    except Exception as e:
        print(f"[review_store] Could not load review queue: {e}")


def save_review_to_disk() -> None:
    try:
        _QUEUE_FILE.write_text(
            json.dumps({"items": list(_review_items.values())}, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[review_store] Could not save review queue: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

def add_to_review_queue(providers: list[dict]) -> int:
    """
    Add providers not already present (no duplicates by NPI).
    Returns count of newly added items.
    """
    added = 0
    for p in providers:
        npi = p.get("npi")
        if not npi or npi in _review_items:
            continue
        now = time.time()
        _review_items[npi] = {
            "npi": npi,
            "risk_score": p.get("risk_score", 0.0),
            "flags": p.get("flags", []),
            "signal_results": p.get("signal_results", []),
            "total_paid": p.get("total_paid", 0),
            "total_claims": p.get("total_claims", 0),
            "status": "pending",
            "notes": "",
            "assigned_to": None,
            "added_at": now,
            "updated_at": now,
            "audit_trail": [],
        }
        added += 1
    if added:
        save_review_to_disk()
    return added


def bulk_update_review_items(npis: list[str], status: str) -> int:
    """Update status for multiple NPIs at once. Returns count of items updated."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {VALID_STATUSES}")
    now = time.time()
    updated = 0
    for npi in npis:
        item = _review_items.get(npi)
        if item:
            previous_status = item["status"]
            item["status"] = status
            item["updated_at"] = now
            # Ensure audit_trail exists (for items created before this feature)
            if "audit_trail" not in item:
                item["audit_trail"] = []
            item["audit_trail"].append({
                "action": "status_change",
                "previous_status": previous_status,
                "new_status": status,
                "timestamp": now,
                "note": "Bulk update",
            })
            updated += 1
    if updated:
        save_review_to_disk()
    return updated


def update_review_item(
    npi: str,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    assigned_to: Optional[str] = ...,  # sentinel: ... means "not provided"
) -> Optional[dict]:
    """Update status, notes, and/or assigned_to for an existing item. Returns updated item or None if not found."""
    item = _review_items.get(npi)
    if item is None:
        return None

    now = time.time()

    # Ensure audit_trail and assigned_to exist (for items created before this feature)
    if "audit_trail" not in item:
        item["audit_trail"] = []
    if "assigned_to" not in item:
        item["assigned_to"] = None

    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}. Must be one of {VALID_STATUSES}")
        previous_status = item["status"]
        item["status"] = status
        item["audit_trail"].append({
            "action": "status_change",
            "previous_status": previous_status,
            "new_status": status,
            "timestamp": now,
            "note": notes if notes is not None else "",
        })

    if notes is not None:
        item["notes"] = notes

    # assigned_to uses sentinel ... to distinguish "not provided" from explicit None (unassign)
    if assigned_to is not ...:
        old_assigned = item.get("assigned_to") or ""
        item["assigned_to"] = assigned_to
        item["audit_trail"].append({
            "action": "assignment_change",
            "previous_status": item["status"],
            "new_status": item["status"],
            "timestamp": now,
            "note": f"Assigned to {assigned_to}" if assigned_to else f"Unassigned (was {old_assigned})",
        })

    item["updated_at"] = now
    save_review_to_disk()
    return item


# ── queries ───────────────────────────────────────────────────────────────────

def get_review_queue(status_filter: Optional[str] = None) -> list[dict]:
    """Return items sorted by risk_score DESC, optionally filtered by status."""
    items = list(_review_items.values())
    if status_filter:
        items = [i for i in items if i["status"] == status_filter]
    items.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return items


def get_review_counts() -> dict:
    items = list(_review_items.values())
    counts = {s: 0 for s in VALID_STATUSES}
    for item in items:
        s = item.get("status", "pending")
        if s in counts:
            counts[s] += 1
    counts["total"] = len(items)
    return counts


def get_review_history(npi: str) -> Optional[list]:
    """Return the audit trail for a specific NPI, or None if not found."""
    item = _review_items.get(npi)
    if item is None:
        return None
    return item.get("audit_trail", [])
