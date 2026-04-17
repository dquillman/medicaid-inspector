"""
Backup & restore service — zips all JSON data files + evidence into timestamped archives.
Auto-cleanup keeps only the last 10 backups.
"""
import json
import os
import pathlib
import shutil
import time
import zipfile
from datetime import datetime, timezone
from typing import Optional

_BACKEND_DIR = pathlib.Path(__file__).parent.parent
_BACKUP_DIR = _BACKEND_DIR / "backups"

# JSON data files to include in backups
_DATA_FILES = [
    "prescan_cache.json",
    "review_queue.json",
    "users.json",
    "enrollment_cache.json",
    "oig_exclusions.json",
    "alert_rules.json",
    "audit_log.json",
    "roi_data.json",
    "watchlist.json",
    "score_history.json",
    "news_alerts.json",
    "notification_store.json",
    "saved_searches.json",
]

# Directories to include
_DATA_DIRS = [
    "evidence",
]


def create_backup() -> dict:
    """
    Create a timestamped backup of all JSON data files and evidence directory.
    Returns metadata about the created backup.
    """
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_id = f"backup_{ts}"
    zip_path = _BACKUP_DIR / f"{backup_id}.zip"

    files_included = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add JSON data files
        for fname in _DATA_FILES:
            fpath = _BACKEND_DIR / fname
            if fpath.exists():
                zf.write(fpath, fname)
                files_included.append(fname)

        # Add evidence directories
        for dname in _DATA_DIRS:
            dpath = _BACKEND_DIR / dname
            if dpath.exists() and dpath.is_dir():
                for root, _dirs, files in os.walk(dpath):
                    for f in files:
                        full = pathlib.Path(root) / f
                        arcname = str(full.relative_to(_BACKEND_DIR))
                        zf.write(full, arcname)
                        files_included.append(arcname)

    size_bytes = zip_path.stat().st_size

    # Auto-cleanup: keep last 10
    _cleanup_old_backups()

    return {
        "backup_id": backup_id,
        "filename": zip_path.name,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1_048_576, 2),
        "files_included": len(files_included),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def list_backups() -> list[dict]:
    """List all available backups with dates and sizes."""
    if not _BACKUP_DIR.exists():
        return []

    backups = []
    for f in sorted(_BACKUP_DIR.glob("backup_*.zip"), reverse=True):
        stat = f.stat()
        # Parse timestamp from filename
        name = f.stem  # e.g. backup_20260310_143500
        ts_str = name.replace("backup_", "")
        try:
            created = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            created = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        # Count files in zip
        try:
            with zipfile.ZipFile(f, "r") as zf:
                file_count = len(zf.namelist())
        except Exception:
            file_count = 0

        backups.append({
            "backup_id": name,
            "filename": f.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / 1_048_576, 2),
            "file_count": file_count,
            "created_at": created.isoformat(),
        })

    return backups


def restore_backup(backup_id: str) -> dict:
    """
    Restore from a backup archive.
    Extracts all files from the backup zip, overwriting current data files.
    Returns info about what was restored.
    """
    zip_path = _BACKUP_DIR / f"{backup_id}.zip"
    if not zip_path.exists():
        return {"error": f"Backup not found: {backup_id}"}

    restored_files = []
    skipped: list[str] = []
    backend_dir_resolved = _BACKEND_DIR.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            # Zip-slip defense: reject absolute paths, traversal components
            # (`..`, `\\`), drive letters, and anything that resolves outside
            # _BACKEND_DIR. A malicious archive could otherwise overwrite any
            # file the server process can write.
            if not member or member.endswith("/"):
                continue
            if (
                member.startswith("/")
                or member.startswith("\\")
                or ".." in pathlib.Path(member).parts
                or (len(member) > 1 and member[1] == ":")
            ):
                skipped.append(member)
                continue

            target = _BACKEND_DIR / member
            try:
                target.resolve().relative_to(backend_dir_resolved)
            except ValueError:
                skipped.append(member)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
            restored_files.append(member)

    return {
        "backup_id": backup_id,
        "restored_files": len(restored_files),
        "files": restored_files,
        "skipped_unsafe": skipped,
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "note": "Restart the server to reload restored data into memory.",
    }


def _cleanup_old_backups(keep: int = 10):
    """Remove old backups, keeping only the most recent `keep` count."""
    if not _BACKUP_DIR.exists():
        return
    backups = sorted(_BACKUP_DIR.glob("backup_*.zip"), reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
