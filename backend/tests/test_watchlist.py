"""
Tests for watchlist CRUD endpoints.
"""
import pytest
from unittest.mock import patch
from core.watchlist_store import load_watchlist_from_disk


@pytest.fixture(autouse=True)
def reset_watchlist(tmp_path):
    """Reset watchlist store for each test."""
    wl_file = tmp_path / "watchlist.json"
    wl_file.write_text("[]")
    with patch("core.watchlist_store._WATCHLIST_FILE", wl_file):
        load_watchlist_from_disk()
        yield


def test_watchlist_empty(client, auth_headers):
    resp = client.get("/api/watchlist", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_add_to_watchlist(client, auth_headers):
    resp = client.post(
        "/api/watchlist",
        headers=auth_headers,
        json={"npi": "1234567890", "reason": "High risk", "alert_threshold": 50},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["npi"] == "1234567890"


def test_add_duplicate_to_watchlist(client, auth_headers):
    client.post("/api/watchlist", headers=auth_headers, json={"npi": "1234567890"})
    resp = client.post("/api/watchlist", headers=auth_headers, json={"npi": "1234567890"})
    assert resp.status_code == 409


def test_remove_from_watchlist(client, auth_headers):
    client.post("/api/watchlist", headers=auth_headers, json={"npi": "1234567890"})
    resp = client.delete("/api/watchlist/1234567890", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_remove_nonexistent_from_watchlist(client, auth_headers):
    resp = client.delete("/api/watchlist/0000000000", headers=auth_headers)
    assert resp.status_code == 404


def test_update_watchlist_entry(client, auth_headers):
    client.post("/api/watchlist", headers=auth_headers, json={"npi": "1234567890"})
    resp = client.patch(
        "/api/watchlist/1234567890",
        headers=auth_headers,
        json={"notes": "Updated notes", "alert_threshold": 75},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["notes"] == "Updated notes"
    assert data["alert_threshold"] == 75


def test_check_watched(client, auth_headers):
    resp = client.get("/api/watchlist/check/1234567890", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["watched"] is False

    client.post("/api/watchlist", headers=auth_headers, json={"npi": "1234567890"})
    resp = client.get("/api/watchlist/check/1234567890", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["watched"] is True


def test_watchlist_alerts(client, auth_headers):
    # Add a provider with a low threshold (risk=65, threshold=50 → should trigger alert)
    client.post(
        "/api/watchlist",
        headers=auth_headers,
        json={"npi": "1234567890", "alert_threshold": 50},
    )
    resp = client.get("/api/watchlist/alerts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert data["total"] >= 1


def test_watchlist_list_after_additions(client, auth_headers):
    client.post("/api/watchlist", headers=auth_headers, json={"npi": "1234567890"})
    client.post("/api/watchlist", headers=auth_headers, json={"npi": "9876543210"})
    resp = client.get("/api/watchlist", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
