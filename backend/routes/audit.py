"""
Audit log API routes.
"""
from typing import Optional
from fastapi import APIRouter, Query, Depends

from core.audit_log import get_audit_log, get_entity_history, get_audit_stats
from routes.auth import require_admin

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("/log")
async def list_audit_log(
    action_type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    date_from: Optional[float] = Query(None),
    date_to: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Paginated audit log with optional filters."""
    filters = {}
    if action_type:
        filters["action_type"] = action_type
    if entity_type:
        filters["entity_type"] = entity_type
    if entity_id:
        filters["entity_id"] = entity_id
    if date_from is not None:
        filters["date_from"] = date_from
    if date_to is not None:
        filters["date_to"] = date_to
    return get_audit_log(filters=filters or None, page=page, limit=limit)


@router.get("/stats")
async def audit_stats():
    """Audit statistics: counts by action type, per-day, most active entities."""
    return get_audit_stats()


@router.get("/log/{entity_type}/{entity_id}")
async def entity_audit_history(entity_type: str, entity_id: str):
    """All audit entries for a specific entity."""
    entries = get_entity_history(entity_type, entity_id)
    return {"entity_type": entity_type, "entity_id": entity_id, "entries": entries}
