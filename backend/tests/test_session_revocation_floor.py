import json
from core import auth_store


def test_revocation_floor_rejects_republished_sessions_at_load_lookup_and_save(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, "_SESSIONS_VALID_AFTER", 1000)
    monkeypatch.setattr(auth_store.time, "time", lambda: 1100)
    monkeypatch.setattr(auth_store, "_SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(auth_store, "_sessions", {})
    monkeypatch.setattr(auth_store, "get_user", lambda name: {"username": name})
    from core import gcs_sync
    monkeypatch.setattr(gcs_sync, "upload_file", lambda name: True)
    old = {"username": "fixture", "created_at": 999, "last_seen": 1090}
    new = {"username": "fixture", "created_at": 1050, "last_seen": 1090}
    auth_store._SESSIONS_FILE.write_text(json.dumps({"old": old, "new": new}))
    auth_store.load_sessions_from_disk()
    assert set(auth_store._sessions) == {"new"}
    auth_store._sessions["old"] = old
    assert auth_store.get_session_user("old") is None
    assert auth_store.get_session_user("new") == {"username": "fixture"}
    auth_store._sessions["old"] = old
    auth_store.save_sessions_to_disk()
    assert set(json.loads(auth_store._SESSIONS_FILE.read_text())) == {"new"}


def test_malformed_and_future_timestamps_are_rejected(monkeypatch):
    monkeypatch.setattr(auth_store, "_SESSIONS_VALID_AFTER", 1000)
    for value in (None, "1001", float("nan"), float("inf"), True, 1200):
        assert not auth_store._session_timestamp_valid({"created_at": value}, 1100)
    assert auth_store._session_timestamp_valid({"created_at": 1000}, 1100)
