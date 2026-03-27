"""Shared fixtures for backend tests."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    """Create a test client for the FastAPI app."""
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    """Login as admin and return the session token."""
    # Try common passwords — admin's password is random on first run
    for pw in ["admin", "password", "test123"]:
        resp = client.post("/api/auth/login", json={"username": "admin", "password": pw})
        if resp.status_code == 200:
            return resp.json()["token"]
    return None


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    """Return Authorization headers for authenticated requests."""
    if auth_token:
        return {"Authorization": f"Bearer {auth_token}"}
    return {}
