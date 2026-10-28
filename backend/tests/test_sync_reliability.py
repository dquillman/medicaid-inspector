"""No cloud calls: fake object generations and disposable SQLite/JSON only."""
import pathlib
import sqlite3
import pytest
from core import gcs_sync as sync
from core.safe_io import atomic_write_json


class PreconditionFailed(Exception):
    code = 412


class Blob:
    def __init__(self, remote):
        self.remote = remote
        self.generation = remote.get("generation")
    def exists(self):
        return self.remote.get("generation") is not None
    def upload_from_filename(self, path, *, if_generation_match):
        actual = self.remote.get("generation", 0)
        if actual != if_generation_match:
            raise PreconditionFailed()
        self.remote["bytes"] = pathlib.Path(path).read_bytes()
        self.remote["generation"] = actual + 1
        self.generation = actual + 1
    def upload_from_string(self, data, *, if_generation_match, **kwargs):
        actual = self.remote.get("generation", 0)
        if actual != if_generation_match:
            raise PreconditionFailed()
        self.remote.update(bytes=data, generation=actual + 1)
        self.generation = actual + 1


class Bucket:
    def __init__(self, objects): self.objects = objects
    def blob(self, name): return Blob(self.objects.setdefault(name, {}))


@pytest.fixture
def state(monkeypatch, tmp_path):
    objects = {}
    monkeypatch.setattr(sync, "_BACKEND_DIR", tmp_path)
    monkeypatch.setattr(sync, "_generations", {})
    monkeypatch.setattr(sync, "_sync_status", {})
    monkeypatch.setattr(sync, "_get_bucket", lambda: Bucket(objects))
    return tmp_path, objects


def test_stale_generation_refuses_overwrite_and_exposes_conflict(state):
    directory, objects = state
    (directory / "review_queue.json").write_text('{"local": true}')
    objects["review_queue.json"] = {"generation": 3, "bytes": b"newer remote"}
    sync._generations["review_queue.json"] = 2
    assert sync._do_upload("review_queue.json") is False
    assert objects["review_queue.json"]["bytes"] == b"newer remote"
    assert sync.get_sync_status()["objects"]["review_queue.json"]["state"] == "conflict"


def test_unknown_existing_object_not_adopted_and_new_object_create_only(state):
    directory, objects = state
    objects["metadata.json"] = {"generation": 9, "bytes": b"protected"}
    assert sync._conditional_upload("metadata.json", lambda blob, expected: blob.upload_from_string(b"replacement", if_generation_match=expected)) is False
    assert objects["metadata.json"]["bytes"] == b"protected"
    assert sync._conditional_upload("new-evidence", lambda blob, expected: blob.upload_from_string(b"evidence", if_generation_match=expected)) is True
    assert sync._generations["new-evidence"] == 1


def test_sqlite_upload_captures_committed_wal_in_consistent_snapshot(state, tmp_path):
    directory, objects = state
    connection = sqlite3.connect(directory / "app.db")
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('committed in WAL')")
        connection.commit()
        assert sync._do_upload("app.db") is True
        restored_path = tmp_path / "restored.db"
        restored_path.write_bytes(objects["app.db"]["bytes"])
        with sqlite3.connect(restored_path) as restored:
            assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert restored.execute("SELECT value FROM evidence").fetchone()[0] == "committed in WAL"
    finally:
        connection.close()


def test_failed_atomic_json_keeps_previous_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"before": true}')
    recursive = []
    recursive.append(recursive)
    with pytest.raises(ValueError):
        atomic_write_json(path, recursive)
    assert path.read_text() == '{"before": true}'
    assert list(tmp_path.glob("*.tmp")) == []


def test_unavailable_upload_not_reported_durable(state, monkeypatch):
    directory, _ = state
    (directory / "state.json").write_text('{}')
    monkeypatch.setattr(sync, "_get_bucket", lambda: None)
    assert sync._do_upload("state.json") is False
    status = sync.get_sync_status()
    assert status["error_count"] == 1
    assert status["objects"]["state.json"]["durable"] is False
