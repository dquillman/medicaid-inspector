"""
Backup & restore API routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_admin
from services.backup import create_backup, list_backups, restore_backup

router = APIRouter(prefix="/api/admin", tags=["backup"], dependencies=[Depends(require_admin)])


@router.post("/backup")
async def trigger_backup():
    """Create a new backup of all data files."""
    try:
        result = create_backup()
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {e}")


@router.get("/backups")
async def get_backups():
    """List all available backups."""
    return {"backups": list_backups()}


@router.post("/restore/{backup_id}")
async def trigger_restore(backup_id: str):
    """Restore data from a backup archive."""
    result = restore_backup(backup_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return {"ok": True, **result}
