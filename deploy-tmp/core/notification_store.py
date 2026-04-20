"""
In-memory + JSON-backed notification store.
Notifications are generated when scans complete, watchlist thresholds breach, or high-risk providers found.
"""
import json
import time
import uuid
import pathlib
from typing import Optional

_NOTIFICATIONS_FILE = pathlib.Path(__file__).parent.parent / "notifications.json"

# In-memory store: list of notification dicts
_notifications: list[dict] = []


def _save_to_disk() -> None:
    try:
        _NOTIFICATIONS_FILE.write_text(
            json.dumps({"notifications": _notifications}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[notification_store] Could not save: {e}")


def load_notifications_from_disk() -> None:
    global _notifications
    try:
        if not _NOTIFICATIONS_FILE.exists():
            return
        raw = json.loads(_NOTIFICATIONS_FILE.read_text(encoding="utf-8"))
        _notifications = raw.get("notifications", [])
        print(f"[notification_store] Loaded {len(_notifications)} notifications from disk")
    except Exception as e:
        print(f"[notification_store] Could not load: {e}")


def add_notification(
    type: str,  # alert | watchlist | scan | system
    title: str,
    message: str,
    link: Optional[str] = None,
) -> dict:
    """Create and store a new notification."""
    notif = {
        "id": str(uuid.uuid4()),
        "type": type,
        "title": title,
        "message": message,
        "timestamp": time.time(),
        "read": False,
        "link": link,
    }
    _notifications.insert(0, notif)
    # Keep only last 200 notifications
    if len(_notifications) > 200:
        _notifications[:] = _notifications[:200]
    _save_to_disk()
    return notif


def list_notifications(limit: int = 50) -> list[dict]:
    """Return notifications sorted: unread first, then by timestamp desc."""
    sorted_notifs = sorted(
        _notifications,
        key=lambda n: (n.get("read", False), -n.get("timestamp", 0)),
    )
    return sorted_notifs[:limit]


def get_unread_count() -> int:
    return sum(1 for n in _notifications if not n.get("read", False))


def mark_read(notification_id: str) -> Optional[dict]:
    for n in _notifications:
        if n["id"] == notification_id:
            n["read"] = True
            _save_to_disk()
            return n
    return None


def mark_all_read() -> int:
    count = 0
    for n in _notifications:
        if not n.get("read", False):
            n["read"] = True
            count += 1
    if count > 0:
        _save_to_disk()
    return count


def notify_scan_complete(providers_scanned: int, high_risk_count: int) -> None:
    """Auto-generate notification when a scan batch completes."""
    add_notification(
        type="scan",
        title="Scan Complete",
        message=f"Scanned {providers_scanned} providers. {high_risk_count} high-risk found.",
        link="/admin/scan",
    )


def notify_high_risk_provider(npi: str, name: str, score: float) -> None:
    """Auto-generate notification for new high-risk provider."""
    add_notification(
        type="alert",
        title="High-Risk Provider Detected",
        message=f"{name or npi} scored {score:.1f} risk score.",
        link=f"/providers/{npi}",
    )


def notify_watchlist_breach(npi: str, name: str, metric: str) -> None:
    """Auto-generate notification when watchlist threshold breached."""
    add_notification(
        type="watchlist",
        title="Watchlist Alert",
        message=f"{name or npi}: {metric} threshold breached.",
        link=f"/providers/{npi}",
    )
