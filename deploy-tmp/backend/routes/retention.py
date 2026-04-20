"""
Data retention policy API routes.
"""
from fastapi import APIRouter, Depends

from core.retention import get_retention_policy, get_retention_status, enforce_retention
from routes.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["retention"], dependencies=[Depends(require_admin)])


@router.get("/retention")
async def retention_status():
    """Current retention status — record counts and oldest records per category."""
    return get_retention_status()


@router.post("/retention/enforce")
async def enforce_retention_policies():
    """Trigger retention enforcement — purge expired records."""
    return enforce_retention()


@router.get("/retention/policy")
async def retention_policy():
    """Show current retention policy definitions."""
    return {"policies": get_retention_policy()}
