"""
PHI access log admin endpoints and middleware setup.
"""
from typing import Optional

from fastapi import APIRouter, Depends

from core.phi_logger import get_phi_log, get_phi_log_stats
from routes.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["phi-log"], dependencies=[Depends(require_admin)])


@router.get("/phi-log")
async def phi_access_log(
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
):
    """View PHI access logs (admin only)."""
    filters = {}
    if user_id:
        filters["user_id"] = user_id
    if resource_type:
        filters["resource_type"] = resource_type
    if resource_id:
        filters["resource_id"] = resource_id
    return get_phi_log(filters=filters or None, page=page, limit=limit)


@router.get("/phi-log/stats")
async def phi_log_stats():
    """PHI access log statistics (admin only)."""
    return get_phi_log_stats()
