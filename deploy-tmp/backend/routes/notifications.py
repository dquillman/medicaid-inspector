"""
Notification endpoints — bell icon notifications for the frontend.
"""
from fastapi import APIRouter, Depends
from routes.auth import require_user
from core.notification_store import (
    list_notifications,
    get_unread_count,
    mark_read,
    mark_all_read,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(require_user)])


@router.get("")
async def get_notifications():
    """List notifications (unread first, limited to 50)."""
    return {
        "notifications": list_notifications(50),
        "unread_count": get_unread_count(),
    }


@router.patch("/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """Mark a single notification as read."""
    notif = mark_read(notification_id)
    if not notif:
        from fastapi import HTTPException
        raise HTTPException(404, "Notification not found")
    return {"ok": True, "notification": notif}


@router.post("/read-all")
async def mark_all_notifications_read():
    """Mark all notifications as read."""
    count = mark_all_read()
    return {"ok": True, "marked_read": count}
