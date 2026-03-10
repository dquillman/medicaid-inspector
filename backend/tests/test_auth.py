"""
Tests for authentication, registration, and token validation.
"""
import pytest


def test_login_success(client):
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "user" in data
    assert data["user"]["username"] == "testuser"


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "wrong"})
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_user(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"] == "testuser"


def test_me_invalid_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken"})
    assert resp.status_code == 401


def test_logout(client, auth_headers):
    resp = client.post("/api/auth/logout", headers=auth_headers)
    assert resp.status_code == 200
    # After logout, /me should fail
    resp2 = client.get("/api/auth/me", headers=auth_headers)
    assert resp2.status_code == 401


def test_list_users_requires_admin(client):
    """List users without auth should return 401."""
    resp = client.get("/api/auth/users")
    assert resp.status_code == 401


def test_list_users_as_admin(client, auth_headers):
    resp = client.get("/api/auth/users", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert any(u["username"] == "testuser" for u in data["users"])


def test_create_user_as_admin(client, auth_headers):
    resp = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "newuser", "password": "pass123", "role": "viewer"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"] == "newuser"
    assert data["user"]["role"] == "viewer"


def test_get_roles(client):
    resp = client.get("/api/auth/roles")
    assert resp.status_code == 200
    data = resp.json()
    assert "roles" in data
    assert "admin" in data["roles"]
