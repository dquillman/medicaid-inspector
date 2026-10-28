"""Synthetic application only: no application startup, stores or cloud calls."""
import asyncio
import threading
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.gcs_sync import _set_status
from core.persistence_middleware import PersistenceAcknowledgementMiddleware


def application():
    app = FastAPI()
    app.add_middleware(PersistenceAcknowledgementMiddleware)

    @app.post("/write/{state}")
    async def write(state: str):
        await asyncio.to_thread(_set_status, "fixture-state", state)
        return {"local_change": True}

    @app.get("/healthy")
    async def healthy():
        # Unrelated worker has no request context. Its global error must not
        # turn this request into a persistence failure.
        worker = threading.Thread(target=_set_status, args=("unrelated", "error"))
        worker.start()
        worker.join()
        return {"healthy": True}

    @app.get("/read")
    async def read():
        _set_status("download", "error", request_write=False)
        return {"read": True}

    return app


def test_request_failure_is_503_and_explicit_about_local_changes():
    with TestClient(application()) as client:
        response = client.post("/write/conflict")
    assert response.status_code == 503
    assert response.headers["x-mfi-persistence"] == "failed"
    assert response.json()["changes_may_exist_locally"] is True
    assert "no rollback" in response.json()["detail"]
    assert "local_change" not in response.json()


def test_pending_is202_and_durable_preserves_success_body():
    with TestClient(application()) as client:
        pending = client.post("/write/pending")
        durable = client.post("/write/synced")
    assert pending.status_code == 202
    assert pending.headers["x-mfi-persistence"] == "pending"
    assert pending.json() == {"local_change": True}
    assert durable.status_code == 200
    assert durable.headers["x-mfi-persistence"] == "durable"


def test_global_errors_read_events_and_previous_request_do_not_contaminate_response():
    with TestClient(application()) as client:
        client.post("/write/error")
        healthy = client.get("/healthy")
        read = client.get("/read")
    assert healthy.status_code == read.status_code == 200
    assert "x-mfi-persistence" not in healthy.headers
    assert "x-mfi-persistence" not in read.headers


def test_concurrent_requests_keep_their_own_events():
    import httpx
    app = FastAPI()
    app.add_middleware(PersistenceAcknowledgementMiddleware)
    gate = asyncio.Event()
    @app.post("/failing")
    async def failing():
        _set_status("fixture-a", "error")
        gate.set()
        await asyncio.sleep(0)
        return {"a": True}
    @app.get("/independent")
    async def independent():
        await gate.wait()
        return {"b": True}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            return await asyncio.gather(client.post("/failing"), client.get("/independent"))
    failed, independent = asyncio.run(run())
    assert failed.status_code == 503
    assert independent.status_code == 200
    assert "x-mfi-persistence" not in independent.headers
