"""
Firestore persistence layer for Medicaid Inspector.
Stores app-specific data under /apps/medicaid-inspector/ in the shared Firestore.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

APP_ID = "medicaid-inspector"
_PREFIX = f"apps/{APP_ID}"


def _get_db():
    """Lazy import to avoid circular deps."""
    from core.firebase_auth import get_firestore_db
    return get_firestore_db()


# ── Alert Rules ──────────────────────────────────────────────────────────────

def load_alert_rules() -> list[dict]:
    """Load alert rules from Firestore."""
    try:
        db = _get_db()
        docs = db.collection(f"{_PREFIX}/alert_rules").stream()
        rules = []
        for doc in docs:
            rule = doc.to_dict()
            rule["id"] = doc.id
            rules.append(rule)
        return rules
    except Exception as e:
        logger.warning(f"[firestore] Could not load alert rules: {e}")
        return []


def save_alert_rule(rule: dict) -> str:
    """Save an alert rule. Returns the document ID."""
    try:
        db = _get_db()
        rule_id = rule.get("id")
        rule_data = {k: v for k, v in rule.items() if k != "id"}
        rule_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        if rule_id:
            db.collection(f"{_PREFIX}/alert_rules").document(rule_id).set(rule_data)
            return rule_id
        else:
            doc_ref = db.collection(f"{_PREFIX}/alert_rules").add(rule_data)
            return doc_ref[1].id
    except Exception as e:
        logger.error(f"[firestore] Could not save alert rule: {e}")
        raise


def delete_alert_rule(rule_id: str) -> bool:
    """Delete an alert rule by ID."""
    try:
        db = _get_db()
        db.collection(f"{_PREFIX}/alert_rules").document(rule_id).delete()
        return True
    except Exception as e:
        logger.warning(f"[firestore] Could not delete alert rule {rule_id}: {e}")
        return False


# ── Review Queue ─────────────────────────────────────────────────────────────

def load_review_items() -> list[dict]:
    """Load review queue items from Firestore."""
    try:
        db = _get_db()
        docs = db.collection(f"{_PREFIX}/review_queue").stream()
        items = []
        for doc in docs:
            item = doc.to_dict()
            item["id"] = doc.id
            items.append(item)
        return items
    except Exception as e:
        logger.warning(f"[firestore] Could not load review queue: {e}")
        return []


def save_review_item(item: dict) -> str:
    """Save a review queue item. Uses NPI as document ID."""
    try:
        db = _get_db()
        npi = str(item.get("npi", ""))
        if not npi:
            raise ValueError("Review item must have an NPI")
        item_data = {k: v for k, v in item.items()}
        item_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        db.collection(f"{_PREFIX}/review_queue").document(npi).set(item_data, merge=True)
        return npi
    except Exception as e:
        logger.error(f"[firestore] Could not save review item: {e}")
        raise


def delete_review_item(npi: str) -> bool:
    """Delete a review queue item."""
    try:
        db = _get_db()
        db.collection(f"{_PREFIX}/review_queue").document(npi).delete()
        return True
    except Exception as e:
        logger.warning(f"[firestore] Could not delete review item {npi}: {e}")
        return False


# ── Watchlist ────────────────────────────────────────────────────────────────

def load_watchlist() -> list[dict]:
    """Load watchlist entries from Firestore."""
    try:
        db = _get_db()
        docs = db.collection(f"{_PREFIX}/watchlist").stream()
        items = []
        for doc in docs:
            item = doc.to_dict()
            item["id"] = doc.id
            items.append(item)
        return items
    except Exception as e:
        logger.warning(f"[firestore] Could not load watchlist: {e}")
        return []


def save_watchlist_entry(entry: dict) -> str:
    """Save a watchlist entry. Uses NPI as document ID."""
    try:
        db = _get_db()
        npi = str(entry.get("npi", ""))
        if not npi:
            raise ValueError("Watchlist entry must have an NPI")
        entry_data = {k: v for k, v in entry.items()}
        entry_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        db.collection(f"{_PREFIX}/watchlist").document(npi).set(entry_data, merge=True)
        return npi
    except Exception as e:
        logger.error(f"[firestore] Could not save watchlist entry: {e}")
        raise


def delete_watchlist_entry(npi: str) -> bool:
    """Delete a watchlist entry."""
    try:
        db = _get_db()
        db.collection(f"{_PREFIX}/watchlist").document(npi).delete()
        return True
    except Exception as e:
        logger.warning(f"[firestore] Could not delete watchlist entry {npi}: {e}")
        return False


# ── Audit Log ────────────────────────────────────────────────────────────────

def append_audit_entry(entry: dict) -> str:
    """Append an audit log entry to Firestore."""
    try:
        db = _get_db()
        entry_data = {k: v for k, v in entry.items()}
        entry_data["app"] = APP_ID
        if "timestamp" not in entry_data:
            entry_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        doc_ref = db.collection(f"{_PREFIX}/audit_log").add(entry_data)
        return doc_ref[1].id
    except Exception as e:
        logger.error(f"[firestore] Could not append audit entry: {e}")
        raise


def load_audit_entries(limit: int = 200, action: Optional[str] = None) -> list[dict]:
    """Load recent audit log entries."""
    try:
        db = _get_db()
        query = db.collection(f"{_PREFIX}/audit_log").order_by(
            "timestamp", direction="DESCENDING"
        ).limit(limit)
        if action:
            query = query.where("action", "==", action)
        docs = query.stream()
        entries = []
        for doc in docs:
            entry = doc.to_dict()
            entry["id"] = doc.id
            entries.append(entry)
        return entries
    except Exception as e:
        logger.warning(f"[firestore] Could not load audit entries: {e}")
        return []


# ── Global Admin Audit ───────────────────────────────────────────────────────

def log_global_admin_action(
    admin_uid: str,
    admin_email: str,
    action: str,
    target_user_id: str = "",
    target_user_email: str = "",
    metadata: dict = None,
    old_values: dict = None,
    new_values: dict = None,
) -> None:
    """Log an action to admin-core's global audit trail."""
    try:
        db = _get_db()
        db.collection("admin_audit").add({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "adminUid": admin_uid,
            "adminEmail": admin_email,
            "action": action,
            "appId": APP_ID,
            "targetUserId": target_user_id,
            "targetUserEmail": target_user_email,
            "metadata": metadata or {},
            "oldValues": old_values or {},
            "newValues": new_values or {},
        })
    except Exception as e:
        logger.warning(f"[firestore] Could not log global admin action: {e}")
