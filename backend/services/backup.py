"""
Backup & restore service — zips all JSON data files + evidence into timestamped archives.
Auto-cleanup keeps only the last 10 backups.
"""
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
import os
import pathlib
import shutil
import time
import zipfile
from datetime import datetime, timezone
from typing import Optional

_BACKEND_DIR = pathlib.Path(__file__).parent.parent
_BACKUP_DIR = _BACKEND_DIR / "backups"

# Mutable state inventory is shared with cloud sync; extra legacy/local caches
# remain included rather than silently dropping older research artifacts.
from core.gcs_sync import _SYNC_FILES
_DATA_FILES = list(dict.fromkeys([*_SYNC_FILES,
    "prescan_cache.json", "enrollment_cache.json", "oig_exclusions.json",
    "news_alerts.json", "notification_store.json",
]))
_MANIFEST = "backup_manifest.json"

# Directories to include
_DATA_DIRS = [
    "evidence",
]


def _digest_stream(stream) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def create_backup() -> dict:
    """Capture per-file consistent snapshots; callers must quiesce mutations
    for cross-file consistency. No cloud data is fetched by this function."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_id = f"backup_{ts}"
    zip_path = _BACKUP_DIR / f"{backup_id}.zip"
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {}, "missing_inventory_files": [],
                "consistency": "per-file snapshots; cross-file consistency requires quiesced mutations",
                "missing_referenced_evidence": []}
    with tempfile.TemporaryDirectory(prefix="mfi-backup-") as temporary:
        snapshot_root = pathlib.Path(temporary)
        snapshots = []
        for name in _DATA_FILES:
            source = _BACKEND_DIR / name
            if not source.exists():
                manifest["missing_inventory_files"].append(name)
                continue
            destination = snapshot_root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == ".db":
                with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as database:
                    with closing(sqlite3.connect(destination)) as snapshot:
                        database.backup(snapshot)
            else:
                shutil.copyfile(source, destination)
            snapshots.append((name, destination))
        for directory in _DATA_DIRS:
            source_dir = _BACKEND_DIR / directory
            if source_dir.is_dir():
                for source in sorted(source_dir.rglob("*")):
                    if source.is_file() and not source.is_symlink():
                        name = source.relative_to(_BACKEND_DIR).as_posix()
                        destination = snapshot_root / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)
                        snapshots.append((name, destination))
        for name, snapshot in snapshots:
            with snapshot.open("rb") as stream:
                digest, size = _digest_stream(stream)
            manifest["files"][name] = {"sha256": digest, "size_bytes": size}
        metadata = snapshot_root / "evidence_metadata.json"
        if metadata.exists():
            evidence = json.loads(metadata.read_text(encoding="utf-8")).get("evidence", {})
            for records in evidence.values():
                for record in records:
                    name = "evidence/" + str(record.get("stored_filename") or "")
                    if name not in manifest["files"]:
                        manifest["missing_referenced_evidence"].append(name)
        staged_zip = snapshot_root / "archive.zip"
        with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, snapshot in snapshots:
                archive.write(snapshot, name)
            archive.writestr(_MANIFEST, json.dumps(manifest, sort_keys=True))
        # copy to same directory then replace, leaving no discoverable partial zip
        partial = zip_path.with_suffix(".partial")
        try:
            shutil.copyfile(staged_zip, partial)
            os.replace(partial, zip_path)
        finally:
            partial.unlink(missing_ok=True)
    _cleanup_old_backups()
    size = zip_path.stat().st_size
    return {"backup_id": backup_id, "filename": zip_path.name, "size_bytes": size,
            "size_mb": round(size / 1_048_576, 2), "files_included": len(manifest["files"]),
            "created_at": manifest["created_at"], "manifest_verified": True,
            "missing_inventory_files": manifest["missing_inventory_files"],
            "missing_referenced_evidence_count": len(manifest["missing_referenced_evidence"]),
            "self_contained_evidence": not manifest["missing_referenced_evidence"]}


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
    """Validate the whole archive before replacing any files. Requires service
    maintenance/restart; this is not a cross-file transaction or cloud restore."""
    if not re.fullmatch(r"backup_\d{8}_\d{6}(?:_\d{6})?", backup_id):
        return {"error": "Invalid backup identifier"}
    zip_path = _BACKUP_DIR / f"{backup_id}.zip"
    if not zip_path.exists():
        return {"error": "Backup not found"}
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or _MANIFEST not in names:
            return {"error": "Archive requires a unique verified inventory manifest; legacy backups need offline inspection"}
        manifest = json.loads(archive.read(_MANIFEST))
        files = manifest.get("files", {})
        if manifest.get("schema_version") != 1 or set(names) != set(files) | {_MANIFEST}:
            return {"error": "Backup manifest inventory mismatch"}
        for name, expected in files.items():
            member = pathlib.PurePosixPath(name)
            if (not name or "\\" in name or member.is_absolute() or ".." in member.parts
                    or ":" in name or not (name in _DATA_FILES or (member.parts[0] in _DATA_DIRS and len(member.parts) > 1))):
                return {"error": "Unsafe or unauthorized backup member"}
            target = (_BACKEND_DIR / name).resolve()
            if not target.is_relative_to(_BACKEND_DIR.resolve()):
                return {"error": "Backup target escapes state directory"}
            with archive.open(name) as stream:
                digest, size = _digest_stream(stream)
            if size != expected["size_bytes"] or digest != expected["sha256"]:
                return {"error": "Backup content hash mismatch"}
        database_module = sys.modules.get("core.database")
        if ("app.db" in files and database_module is not None and getattr(database_module, "_conn", None) is not None
                and pathlib.Path(database_module._DB_PATH).resolve() == (_BACKEND_DIR / "app.db").resolve()):
            return {"error": "Close the application database in maintenance mode before restore"}
        for name in files:
            if name.endswith(".db") and any((_BACKEND_DIR / (name + suffix)).exists() for suffix in ("-wal", "-shm")):
                return {"error": "SQLite WAL/SHM files remain; close connections and reconcile in maintenance mode before restore"}
        with tempfile.TemporaryDirectory(prefix="mfi-restore-") as temporary:
            staging = pathlib.Path(temporary)
            for name in files:
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                if destination.suffix == ".db":
                    with closing(sqlite3.connect(destination)) as connection:
                        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            return {"error": "Backup SQLite integrity check failed"}
            # Integrity and path validation finish before any operator state write.
            for name in files:
                destination = _BACKEND_DIR / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_name(destination.name + ".restore-partial")
                try:
                    shutil.copyfile(staging / name, partial)
                    os.replace(partial, destination)
                finally:
                    partial.unlink(missing_ok=True)
    return {"backup_id": backup_id, "restored_files": len(files), "files": list(files),
            "manifest_verified": True, "restored_at": datetime.now(timezone.utc).isoformat(),
            "missing_referenced_evidence_count": len(manifest.get("missing_referenced_evidence", [])),
            "note": "Restart service to reload state. Cloud objects were not restored. Per-file replacements are not a cross-file transaction."}


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
