"""
Backup & restore API routes.
"""
import re
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_admin
from services.backup import create_backup, list_backups, restore_backup

router = APIRouter(prefix="/api/admin", tags=["backup"], dependencies=[Depends(require_admin)])

# Allowed backup_id format: backup_YYYYMMDD_HHMMSS — rejects path traversal attempts
_BACKUP_ID_RE = re.compile(r"^backup_\d{8}_\d{6}$")


@router.post("/backup")
async def trigger_backup():
    """Create a new backup of all data files."""
    try:
        result = create_backup()
        return {"ok": True, **result}
    except Exception as e:
        # Avoid leaking filesystem paths in error messages
        raise HTTPException(500, "Backup failed — check server logs for details")


@router.get("/backups")
async def get_backups():
    """List all available backups."""
    return {"backups": list_backups()}


@router.post("/restore/{backup_id}")
async def trigger_restore(backup_id: str):
    """Restore data from a backup archive."""
    # Validate backup_id to prevent path traversal
    if not _BACKUP_ID_RE.match(backup_id):
        raise HTTPException(400, "Invalid backup_id format")
    result = restore_backup(backup_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return {"ok": True, **result}
