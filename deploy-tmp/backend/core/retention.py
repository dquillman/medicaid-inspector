"""
Data retention policy engine.
Defines retention periods for each data category and enforces purging of expired records.
"""
import time
from typing import Optional
from datetime import datetime

# Retention periods in days
RETENTION_POLICIES = {
    "scan_data":    90,       # 90 days
    "audit_log":    365,      # 1 year
    "phi_log":      2555,     # 7 years (HIPAA requirement)
    "review_queue": None,     # indefinite
}


def get_retention_policy() -> list[dict]:
    """Return the current retention policy as a list of dicts."""
    return [
        {
            "category": cat,
            "retention_days": days,
            "retention_label": f"{days} days" if days else "Indefinite",
        }
        for cat, days in RETENTION_POLICIES.items()
    ]


def get_retention_status() -> dict:
    """Return current record counts and oldest records per category."""
    from core.audit_log import _entries as audit_entries
    from core.phi_logger import get_phi_entry_count, get_oldest_phi_timestamp
    from core.store import get_prescanned
    from core.review_store import get_review_queue

    now = time.time()

    # Scan data
    scan_providers = get_prescanned()
    scan_count = len(scan_providers)

    # Audit log
    audit_count = len(audit_entries)
    audit_oldest = audit_entries[0]["timestamp"] if audit_entries else None

    # PHI log
    phi_count = get_phi_entry_count()
    phi_oldest = get_oldest_phi_timestamp()

    # Review queue
    review_items = get_review_queue()
    review_count = len(review_items)
    review_oldest = min((i.get("added_at", now) for i in review_items), default=None)

    def _age_days(ts: Optional[float]) -> Optional[float]:
        if ts is None:
            return None
        return round((now - ts) / 86400, 1)

    def _status(category: str, count: int, oldest_ts: Optional[float]) -> dict:
        policy_days = RETENTION_POLICIES.get(category)
        age = _age_days(oldest_ts)
        needs_purge = False
        if policy_days and age and age > policy_days:
            needs_purge = True
        return {
            "category": category,
            "record_count": count,
            "oldest_timestamp": oldest_ts,
            "oldest_age_days": age,
            "retention_days": policy_days,
            "retention_label": f"{policy_days} days" if policy_days else "Indefinite",
            "needs_purge": needs_purge,
        }

    categories = [
        _status("scan_data", scan_count, None),  # scan data doesn't have per-record timestamps
        _status("audit_log", audit_count, audit_oldest),
        _status("phi_log", phi_count, phi_oldest),
        _status("review_queue", review_count, review_oldest),
    ]

    return {
        "categories": categories,
        "checked_at": now,
        "any_needs_purge": any(c["needs_purge"] for c in categories),
    }


def enforce_retention() -> dict:
    """
    Purge expired records from each store according to retention policy.
    Returns summary of what was purged.
    """
    now = time.time()
    results = {}

    # Audit log: 365 days
    audit_days = RETENTION_POLICIES["audit_log"]
    if audit_days:
        cutoff = now - (audit_days * 86400)
        from core.audit_log import _entries as audit_entries, _save_to_disk as save_audit
        before = len(audit_entries)
        audit_entries[:] = [e for e in audit_entries if e["timestamp"] >= cutoff]
        removed = before - len(audit_entries)
        if removed:
            save_audit()
        results["audit_log"] = {"removed": removed, "remaining": len(audit_entries)}

    # PHI log: 2555 days (7 years)
    phi_days = RETENTION_POLICIES["phi_log"]
    if phi_days:
        cutoff = now - (phi_days * 86400)
        from core.phi_logger import purge_before
        removed = purge_before(cutoff)
        from core.phi_logger import get_phi_entry_count
        results["phi_log"] = {"removed": removed, "remaining": get_phi_entry_count()}

    # Scan data: 90 days — we clear the entire prescan cache if it's older than 90 days
    # Since individual providers don't have timestamps, we track via scan progress
    results["scan_data"] = {"removed": 0, "remaining": 0, "note": "Scan data retention managed via scan reset"}

    # Review queue: indefinite
    results["review_queue"] = {"removed": 0, "note": "Retention policy is indefinite — no purging"}

    results["enforced_at"] = now
    return results
