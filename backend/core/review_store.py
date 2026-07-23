"""
Persistent storage for flagged provider review cases.
Disk file: backend/review_queue.json
"""
import json
import time
import pathlib
import threading
from typing import Optional

from core.safe_io import atomic_write_json

_QUEUE_FILE = pathlib.Path(__file__).parent.parent / "review_queue.json"

# In-memory store: NPI -> item dict
_review_items: dict[str, dict] = {}
_review_lock = threading.Lock()

VALID_STATUSES = {"pending", "assigned", "investigating", "confirmed_fraud", "referred", "dismissed"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}

# ── Case-ledger status (queue_status) ─────────────────────────────────────────
# The canonical *case ledger* state for an NPI, DELIBERATELY DECOUPLED from the
# live-computed Fraud Brain risk score: it is written only by explicit human
# action and never recomputed from billing data, so it does not flicker as the
# score refreshes. The Fraud Brain may READ this (for badges / de-prioritising
# already-actioned providers) but must NEVER write it, and it must never feed
# back into the computed risk score. One-way, read-only.
# 'archived' = closed WITHOUT judgment ("too old / not pursuing") — unlike
# 'dismissed' ("a human judged this NOT fraud") it is NEVER a training label,
# so bulk-archiving stale cases can't poison the supervised model.
VALID_QUEUE_STATUSES = {"open", "under_review", "tip_filed", "dismissed", "confirmed", "referred", "archived"}
DEFAULT_QUEUE_STATUS = "open"
# Transitions that carry real-world weight — confirming fraud, and the two
# reporting settings ('tip_filed' = Reported: OIG hotline tip; 'referred' =
# Reported: MFCU state referral) — must be a deliberate HUMAN action, never an
# automatic side effect of an AI drafting a document. Enforced in
# set_queue_status by requiring actor_type == "user".
HUMAN_GATED_QUEUE_STATUSES = {"confirmed", "referred", "tip_filed"}
VALID_ACTOR_TYPES = {"user", "system", "ai"}


def _queue_status_of(item: dict) -> str:
    """queue_status for an item, defaulting for rows created before this field."""
    return item.get("queue_status") or DEFAULT_QUEUE_STATUS


# ── disk persistence ──────────────────────────────────────────────────────────

def load_review_from_disk() -> None:
    global _review_items
    try:
        if not _QUEUE_FILE.exists():
            return
        text = _QUEUE_FILE.read_text(encoding="utf-8").strip()
        if not text:
            # File is empty — treat as fresh/empty queue
            with _review_lock:
                _review_items = {}
            print("[review_store] review_queue.json is empty — starting with empty queue")
            return
        raw = json.loads(text)
        loaded = {item["npi"]: item for item in raw.get("items", [])}
        with _review_lock:
            _review_items = loaded
        print(f"[review_store] Loaded {len(_review_items)} review items from disk")
    except Exception as e:
        print(f"[review_store] Could not load review queue: {e}")


def save_review_to_disk() -> None:
    # Caller must hold _review_lock or operate on a snapshot — we snapshot here.
    with _review_lock:
        snapshot = list(_review_items.values())
    try:
        atomic_write_json(_QUEUE_FILE, {"items": snapshot})
        # Sync to GCS so data survives container restarts on Cloud Run
        try:
            from core.gcs_sync import upload_file
            upload_file("review_queue.json")
        except Exception:
            pass  # GCS not available locally — that's fine
    except Exception as e:
        print(f"[review_store] Could not save review queue: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

def add_to_review_queue(providers: list[dict]) -> int:
    """
    Add providers not already present (no duplicates by NPI).
    Returns count of newly added items.
    """
    now = time.time()
    added = 0
    with _review_lock:
        for p in providers:
            npi = p.get("npi")
            if not npi or npi in _review_items:
                continue
            _review_items[npi] = {
                "npi": npi,
                "risk_score": p.get("risk_score", 0.0),
                "flags": p.get("flags", []),
                "signal_results": p.get("signal_results", []),
                "total_paid": p.get("total_paid", 0),
                "total_claims": p.get("total_claims", 0),
                "status": "pending",
                # Case-ledger state — every promoted NPI enters at "open". Only an
                # explicit human action advances it (see set_queue_status).
                "queue_status": DEFAULT_QUEUE_STATUS,
                "notes": "",
                "assigned_to": None,
                "added_at": now,
                "updated_at": now,
                "audit_trail": [{
                    "action": "queue_status_change",
                    "previous_queue_status": None,
                    "new_queue_status": DEFAULT_QUEUE_STATUS,
                    "actor": p.get("_promoted_by") or "system",
                    "actor_type": "user" if p.get("_promoted_by") else "system",
                    "timestamp": now,
                    "note": "Promoted into review queue",
                }],
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
    with _review_lock:
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
    # Validate status before acquiring lock to fail fast without holding the lock
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {VALID_STATUSES}")

    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None

        # Ensure audit_trail and assigned_to exist (for items created before this feature)
        if "audit_trail" not in item:
            item["audit_trail"] = []
        if "assigned_to" not in item:
            item["assigned_to"] = None

        if status is not None:
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
                "previous_assigned_to": old_assigned,
                "new_assigned_to": assigned_to or "",
                "timestamp": now,
                "note": f"Assigned to {assigned_to}" if assigned_to else f"Unassigned (was {old_assigned})",
            })

        item["updated_at"] = now
        result = dict(item)
    save_review_to_disk()
    return result


def bulk_archive(npis_with_meta: list[dict], *, actor: str) -> dict:
    """Archive many providers in ONE pass with ONE disk/GCS save.

    For each entry ({npi, risk_score?, flags?, total_paid?, total_claims?}):
      - creates a queue item if the NPI has none (so never-worked stale
        providers can enter the archive), then
      - sets queue_status='archived' with a full audit entry — UNLESS the case
        is in a protected state: confirmed/referred/tip_filed (real judgments /
        proof-of-filing records) or dismissed (a training label) or already
        archived. Protected cases are counted and left untouched.

    Per-call set_queue_status would save 6k+ times; this exists precisely so a
    bulk archive is one lock + one save."""
    now = time.time()
    archived = created = protected = already = 0
    protected_states = {"confirmed", "referred", "tip_filed", "dismissed"}
    with _review_lock:
        for meta in npis_with_meta:
            npi = meta.get("npi")
            if not npi:
                continue
            item = _review_items.get(npi)
            if item is None:
                item = {
                    "npi": npi,
                    "risk_score": meta.get("risk_score", 0),
                    "flags": meta.get("flags", []),
                    "signal_results": [],
                    "total_paid": meta.get("total_paid", 0),
                    "total_claims": meta.get("total_claims", 0),
                    "status": "pending",
                    "queue_status": DEFAULT_QUEUE_STATUS,
                    "notes": "",
                    "assigned_to": None,
                    "added_at": now,
                    "updated_at": now,
                    "audit_trail": [],
                }
                _review_items[npi] = item
                created += 1
            current = _queue_status_of(item)
            if current == "archived":
                already += 1
                continue
            if current in protected_states:
                protected += 1
                continue
            item.setdefault("audit_trail", []).append({
                "action": "queue_status_change",
                "previous_queue_status": current,
                "new_queue_status": "archived",
                "actor": actor or "unknown",
                "actor_type": "user",
                "timestamp": now,
                "note": "Bulk archive (stale cleanup) — closed without judgment",
            })
            item["queue_status"] = "archived"
            item["queue_status_updated_at"] = now
            item["updated_at"] = now
            archived += 1
    save_review_to_disk()
    return {"archived": archived, "created": created,
            "protected_skipped": protected, "already_archived": already}


def get_archived_items(page: int = 1, limit: int = 50) -> dict:
    """Paginated list of archived cases from the FULL store (they are hidden
    from the main queue view — the archive is its own surface)."""
    with _review_lock:
        items = [dict(i) for i in _review_items.values()
                 if _queue_status_of(i) == "archived"]
    items.sort(key=lambda x: -(x.get("queue_status_updated_at") or x.get("updated_at") or 0))
    total = len(items)
    start = (max(1, page) - 1) * limit
    return {"items": items[start:start + limit], "total": total, "page": page}


# ── case-ledger status (queue_status) mutations ───────────────────────────────

class QueueStatusError(Exception):
    """Raised when a queue_status transition is rejected (bad value, or a
    human-gated transition attempted by a non-human actor)."""


def set_queue_status(
    npi: str,
    new_status: str,
    *,
    actor: str,
    actor_type: str = "user",
    note: str = "",
) -> Optional[dict]:
    """Explicitly set the case-ledger status for an NPI already in the queue.

    - Never auto-creates a queue entry: returns None if the NPI isn't in the
      queue (promotion is a separate, deliberate step — the Fraud Brain surfacing
      a candidate must NOT drag it into the ledger).
    - Human-gated transitions (tip_filed / confirmed) require actor_type=="user";
      an AI/system caller is refused, so drafting a tip can never *record* that a
      tip was filed as a side effect.
    - Appends a full audit entry (prior state, actor, actor_type, timestamp).

    Raises QueueStatusError on an invalid status value or a refused human-gated
    transition. Returns the updated item, or None if the NPI isn't in the queue.
    """
    if new_status not in VALID_QUEUE_STATUSES:
        raise QueueStatusError(
            f"Invalid queue_status {new_status!r}. Must be one of {sorted(VALID_QUEUE_STATUSES)}"
        )
    if actor_type not in VALID_ACTOR_TYPES:
        raise QueueStatusError(
            f"Invalid actor_type {actor_type!r}. Must be one of {sorted(VALID_ACTOR_TYPES)}"
        )
    if new_status in HUMAN_GATED_QUEUE_STATUSES and actor_type != "user":
        raise QueueStatusError(
            f"Transition to {new_status!r} must be a human-initiated action "
            f"(actor_type='user'); refused for actor_type={actor_type!r}. Record "
            f"this from the review UI, not automatically."
        )

    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None  # not in queue — no auto-create
        if "audit_trail" not in item:
            item["audit_trail"] = []
        previous = _queue_status_of(item)
        item["queue_status"] = new_status
        item["queue_status_updated_at"] = now
        item["updated_at"] = now
        item["audit_trail"].append({
            "action": "queue_status_change",
            "previous_queue_status": previous,
            "new_queue_status": new_status,
            "actor": actor or "unknown",
            "actor_type": actor_type,
            "timestamp": now,
            "note": note or "",
        })
        result = dict(item)
    save_review_to_disk()
    return result


# ── case notes (append-only log) ──────────────────────────────────────────────
# The case-note log is the investigator's on-the-record narrative: append-only,
# timestamped, authored (human vs AI tagged). It deliberately CANNOT be edited —
# corrections are new notes. The single editable `notes` string above remains
# the case SUMMARY (current thinking); this log is the permanent record. The
# only mutation besides append is an admin redact, which blanks the text but
# leaves a tombstone + audit entry so the record never silently shrinks.

MAX_CASE_NOTE_CHARS = 4000


class CaseNoteError(Exception):
    """Raised when a case-note operation is rejected (bad input, missing note)."""


def add_case_note(npi: str, text: str, *, actor: str, actor_type: str = "user") -> Optional[dict]:
    """Append a note to an NPI's case log. Returns the new note entry, or None
    if the NPI isn't in the queue (no auto-create — same rule as set_queue_status)."""
    if actor_type not in VALID_ACTOR_TYPES:
        raise CaseNoteError(
            f"Invalid actor_type {actor_type!r}. Must be one of {sorted(VALID_ACTOR_TYPES)}"
        )
    text = (text or "").strip()
    if not text:
        raise CaseNoteError("Note text is empty.")
    if len(text) > MAX_CASE_NOTE_CHARS:
        raise CaseNoteError(f"Note exceeds {MAX_CASE_NOTE_CHARS} characters.")

    import uuid
    now = time.time()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "actor": actor or "unknown",
        "actor_type": actor_type,
        "created_at": now,
        "redacted": False,
    }
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        item.setdefault("case_notes", []).append(entry)
        if "audit_trail" not in item:
            item["audit_trail"] = []
        item["audit_trail"].append({
            "action": "case_note_added",
            "note_id": entry["id"],
            "actor": entry["actor"],
            "actor_type": actor_type,
            "timestamp": now,
            "note": text[:80],
        })
        item["updated_at"] = now
        result = dict(entry)
    save_review_to_disk()
    return result


def redact_case_note(npi: str, note_id: str, *, actor: str) -> Optional[dict]:
    """Admin-only (enforced at the route layer): blank a note's text, leaving a
    tombstone. Returns the tombstoned entry, None if the NPI isn't in the queue.
    Raises CaseNoteError if the note id doesn't exist or is already redacted."""
    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        note = next((n for n in item.get("case_notes", []) if n.get("id") == note_id), None)
        if note is None:
            raise CaseNoteError(f"No case note {note_id!r} on NPI {npi}.")
        if note.get("redacted"):
            raise CaseNoteError(f"Case note {note_id!r} is already redacted.")
        note["text"] = ""
        note["redacted"] = True
        note["redacted_by"] = actor or "unknown"
        note["redacted_at"] = now
        if "audit_trail" not in item:
            item["audit_trail"] = []
        item["audit_trail"].append({
            "action": "case_note_redacted",
            "note_id": note_id,
            "actor": actor or "unknown",
            "actor_type": "user",
            "timestamp": now,
            "note": "Note redacted (tombstone retained)",
        })
        item["updated_at"] = now
        result = dict(note)
    save_review_to_disk()
    return result


def get_case_notes(npi: str) -> Optional[list[dict]]:
    """The case-note log for an NPI (oldest first), or None if not in the queue."""
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        return [dict(n) for n in item.get("case_notes", [])]


def get_queue_status(npi: str) -> Optional[str]:
    """Case-ledger status for an NPI, or None if it's not in the queue."""
    with _review_lock:
        item = _review_items.get(npi)
        return _queue_status_of(item) if item is not None else None


def get_queue_statuses(npis: list[str]) -> dict[str, str]:
    """Batch read of queue_status for many NPIs. Only NPIs actually in the queue
    appear in the result — callers (e.g. the Fraud Brain badge) treat a missing
    key as 'not in queue'. READ-ONLY: this is the one-way link from ledger to
    the candidate engine."""
    wanted = set(npis)
    with _review_lock:
        return {
            npi: _queue_status_of(item)
            for npi, item in _review_items.items()
            if npi in wanted
        }


# ── queries ───────────────────────────────────────────────────────────────────

def get_review_queue(status_filter: Optional[str] = None) -> list[dict]:
    """Return items sorted by risk_score DESC, optionally filtered by status."""
    with _review_lock:
        items = list(_review_items.values())
    if status_filter:
        items = [i for i in items if i["status"] == status_filter]
    items.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return items


def get_review_counts() -> dict:
    with _review_lock:
        items = list(_review_items.values())
    counts = {s: 0 for s in VALID_STATUSES}
    for item in items:
        s = item.get("status", "pending")
        if s in counts:
            counts[s] += 1
    counts["total"] = len(items)
    counts["stale"] = sum(1 for i in items if is_stale_case(i))
    return counts


# ── stale-case detection (#6) ─────────────────────────────────────────────────
# A case parked in an ACTIVE ledger state (open / under_review) with no
# queue_status change for this many days is "stale" — it needs a nudge so cases
# don't sit under review indefinitely. Resolved states (tip_filed / confirmed /
# referred / dismissed) are terminal and never stale.
STALE_CASE_DAYS = 14
_STALE_ACTIVE_STATES = {"open", "under_review"}


def _case_last_activity(item: dict) -> float:
    """Best available 'last touched' timestamp for staleness: the last
    queue_status change, else last update, else when it was added."""
    return (
        item.get("queue_status_updated_at")
        or item.get("updated_at")
        or item.get("added_at")
        or 0.0
    )


def is_stale_case(item: dict, days: int = STALE_CASE_DAYS) -> bool:
    if _queue_status_of(item) not in _STALE_ACTIVE_STATES:
        return False
    last = _case_last_activity(item)
    return bool(last) and (time.time() - last) > days * 86400


def case_stale_days(item: dict) -> Optional[int]:
    """Whole days since last activity for an active case, else None."""
    if _queue_status_of(item) not in _STALE_ACTIVE_STATES:
        return None
    last = _case_last_activity(item)
    if not last:
        return None
    return int((time.time() - last) // 86400)


def get_stale_cases(days: int = STALE_CASE_DAYS) -> list[dict]:
    """Active cases (open / under_review) untouched for >= `days`, oldest first."""
    with _review_lock:
        items = list(_review_items.values())
    stale = [dict(i) for i in items if is_stale_case(i, days)]
    stale.sort(key=_case_last_activity)  # oldest activity first
    return stale


def get_review_history(npi: str) -> Optional[list]:
    """Return the audit trail for a specific NPI, or None if not found."""
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        return list(item.get("audit_trail", []))


def get_review_item(npi: str) -> Optional[dict]:
    """Return a single review item by NPI, or None."""
    with _review_lock:
        item = _review_items.get(npi)
        return dict(item) if item is not None else None


# ── case management extensions ───────────────────────────────────────────────

def add_document(npi: str, doc: dict) -> Optional[dict]:
    """Add a document record to a review case. Returns updated item or None."""
    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        if "documents" not in item:
            item["documents"] = []
        doc["added_at"] = now
        item["documents"].append(doc)
        item["updated_at"] = now
        result = dict(item)
    save_review_to_disk()
    return result


def log_hours(npi: str, hours: float, description: str = "") -> Optional[dict]:
    """Log investigator hours on a case. Returns updated item or None."""
    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        if "hours_logged" not in item:
            item["hours_logged"] = []
        item["hours_logged"].append({
            "hours": hours,
            "description": description,
            "logged_at": now,
        })
        item["total_hours"] = sum(h["hours"] for h in item["hours_logged"])
        item["updated_at"] = now
        result = dict(item)
    save_review_to_disk()
    return result


def set_priority(npi: str, priority: str) -> Optional[dict]:
    """Set case priority. Raises ValueError for invalid priority."""
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"Invalid priority: {priority!r}. Must be one of {VALID_PRIORITIES}")
    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        item["priority"] = priority
        item["updated_at"] = now
        result = dict(item)
    save_review_to_disk()
    return result


def set_due_date(npi: str, due_date: Optional[str]) -> Optional[dict]:
    """Set or clear case due date (ISO date string). Returns updated item or None."""
    now = time.time()
    with _review_lock:
        item = _review_items.get(npi)
        if item is None:
            return None
        item["due_date"] = due_date
        item["updated_at"] = now
        result = dict(item)
    save_review_to_disk()
    return result


def get_case_stats() -> dict:
    """Return aggregate case management statistics."""
    with _review_lock:
        items = list(_review_items.values())
    now = time.time()
    total = len(items)
    by_status = {}
    by_priority = {}
    total_hours = 0.0
    overdue = 0

    for item in items:
        s = item.get("status", "pending")
        by_status[s] = by_status.get(s, 0) + 1
        p = item.get("priority", "medium")
        by_priority[p] = by_priority.get(p, 0) + 1
        total_hours += item.get("total_hours", 0.0)
        dd = item.get("due_date")
        if dd and s not in ("confirmed_fraud", "referred", "dismissed"):
            # Simple ISO date comparison
            try:
                import datetime
                if datetime.date.fromisoformat(dd) < datetime.date.today():
                    overdue += 1
            except (ValueError, TypeError):
                pass

    return {
        "total_cases": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "total_hours": round(total_hours, 1),
        "overdue_count": overdue,
    }


def get_overdue_cases() -> list[dict]:
    """Return cases past their due date that are still open."""
    import datetime
    now = datetime.date.today()
    open_statuses = {"pending", "assigned", "investigating"}
    result = []
    with _review_lock:
        items_snapshot = list(_review_items.values())
    for item in items_snapshot:
        if item.get("status", "pending") not in open_statuses:
            continue
        dd = item.get("due_date")
        if not dd:
            continue
        try:
            if datetime.date.fromisoformat(dd) < now:
                result.append(item)
        except (ValueError, TypeError):
            pass
    result.sort(key=lambda x: x.get("due_date", ""))
    return result
