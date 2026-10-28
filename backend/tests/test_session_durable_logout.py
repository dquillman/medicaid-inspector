import json
from core import auth_store, gcs_sync


def test_login_and_logout_persist_immediately_and_survive_reload(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, "_SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(auth_store, "_sessions", {})
    monkeypatch.setattr(auth_store, "_SESSIONS_VALID_AFTER", 0)
    uploads = []
    def upload(name, *, immediate=False):
        assert name == "sessions.json" and immediate is True
        uploads.append(json.loads(auth_store._SESSIONS_FILE.read_text()))
        return True
    monkeypatch.setattr(gcs_sync, "upload_file", upload)
    token = auth_store.create_session("fixture")
    assert token in uploads[-1]
    assert auth_store.invalidate_session(token)
    assert uploads[-1] == {}
    auth_store.load_sessions_from_disk()
    assert auth_store.get_session_user(token) is None


def test_immediate_session_upload_cancels_pending_timer(monkeypatch):
    # The suite deliberately replaces the shared module's public upload API.
    # Load this unit independently, then replace its only I/O operation.
    import importlib.util
    spec = importlib.util.spec_from_file_location("isolated_session_sync", gcs_sync.__file__)
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    class Timer:
        cancelled = False
        def cancel(self): self.cancelled = True
    timer = Timer()
    monkeypatch.setattr(sync, "_pending_timers", {"sessions.json": timer})
    monkeypatch.setattr(sync, "_last_upload", {"sessions.json": sync.time.time()})
    monkeypatch.setattr(sync, "_do_upload", lambda name: name == "sessions.json")
    assert sync.upload_file("sessions.json", immediate=True)
    assert timer.cancelled
    assert "sessions.json" not in sync._pending_timers
