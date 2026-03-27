import pytest
"""Basic health and auth endpoint tests."""


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


def test_login_invalid_credentials(client):
    resp = client.post("/api/auth/login", json={"username": "nonexistent", "password": "wrong"})
    assert resp.status_code == 401


def test_roles_endpoint_is_public(client):
    resp = client.get("/api/auth/roles")
    assert resp.status_code == 200
    assert "roles" in resp.json()


def test_protected_endpoint_requires_auth(client):
    resp = client.get("/api/summary")
    assert resp.status_code == 401


def test_protected_endpoint_with_auth(client, auth_headers):
    if not auth_headers:
        pytest.skip("No auth token available")
    resp = client.get("/api/summary", headers=auth_headers)
    assert resp.status_code == 200


def test_prescan_status_with_auth(client, auth_headers):
    if not auth_headers:
        pytest.skip("No auth token available")
    resp = client.get("/api/prescan/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "phase" in data
    assert "auto_mode" in data
