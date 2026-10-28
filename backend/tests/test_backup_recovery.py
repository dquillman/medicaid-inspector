"""Complete synthetic recovery exercise; no operator state or cloud access."""
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
import pytest
from core.gcs_sync import _SYNC_FILES
from services import backup


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    root = tmp_path / "synthetic-backend"
    root.mkdir()
    monkeypatch.setattr(backup, "_BACKEND_DIR", root)
    monkeypatch.setattr(backup, "_BACKUP_DIR", root / "backups")
    return root


def test_full_inventory_wal_and_evidence_restore_verified(isolated):
    root = isolated
    assert set(_SYNC_FILES) <= set(backup._DATA_FILES)
    # Every state file is synthetic; parquet/index names contain fixture bytes,
    # not a provider dataset. SQLite and metadata use their actual formats.
    for name in backup._DATA_FILES:
        if name != "app.db":
            (root / name).write_text(json.dumps({"fixture": name}))
    evidence_dir = root / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "fixture-evidence.txt").write_bytes(b"synthetic custody bytes")
    (root / "evidence_metadata.json").write_text(json.dumps({"evidence": {"fixture-case": [{"stored_filename": "fixture-evidence.txt"}]}}))
    source = sqlite3.connect(root / "app.db")
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE custody(value TEXT)")
        source.execute("INSERT INTO custody VALUES ('committed in WAL')")
        source.commit()
        result = backup.create_backup()
    finally:
        source.close()
    assert result["self_contained_evidence"] is True
    assert result["missing_inventory_files"] == []
    archive_path = root / "backups" / result["filename"]
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("backup_manifest.json"))
    for name in manifest["files"]:
        (root / name).write_bytes(b"intentionally changed fixture")
    restored = backup.restore_backup(result["backup_id"])
    assert restored["manifest_verified"] is True
    assert restored["restored_files"] == len(manifest["files"])
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected["sha256"]
    with closing(sqlite3.connect(root / "app.db")) as restored_db:
        assert restored_db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored_db.execute("SELECT value FROM custody").fetchone()[0] == "committed in WAL"


def test_corrupt_backup_rejected_before_any_state_write(isolated):
    root = isolated
    (root / "review_queue.json").write_text('{"fixture":"original"}')
    result = backup.create_backup()
    path = root / "backups" / result["filename"]
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["review_queue.json"] = b"tampered"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items(): archive.writestr(name, content)
    (root / "review_queue.json").write_text("current fixture remains")
    assert "hash mismatch" in backup.restore_backup(result["backup_id"])["error"]
    assert (root / "review_queue.json").read_text() == "current fixture remains"


def test_remote_only_evidence_gap_is_reported(isolated):
    (isolated / "evidence_metadata.json").write_text(json.dumps({"evidence": {"fixture": [{"stored_filename": "not-cached.txt"}]}}))
    result = backup.create_backup()
    assert result["missing_referenced_evidence_count"] == 1
    assert result["self_contained_evidence"] is False


def test_backup_identifier_path_traversal_rejected(isolated):
    assert "error" in backup.restore_backup("../../outside")
