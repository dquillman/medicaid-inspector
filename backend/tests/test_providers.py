"""
Tests for provider list, detail, and search endpoints.
"""
import pytest


def test_provider_list_returns_data(client, auth_headers):
    resp = client.get("/api/providers", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "total" in data
    assert data["total"] == 3


def test_provider_list_pagination(client, auth_headers):
    resp = client.get("/api/providers?page=1&limit=1", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["providers"]) == 1
    assert data["page"] == 1
    assert data["limit"] == 1


def test_provider_list_search(client, auth_headers):
    resp = client.get("/api/providers?search=Test+Provider+A", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    # Should find our seeded provider
    npis = [p["npi"] for p in data["providers"]]
    assert "1234567890" in npis


def test_provider_list_state_filter(client, auth_headers):
    resp = client.get("/api/providers?states=TX", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # We have 2 TX providers
    assert data["total"] == 2
    for p in data["providers"]:
        assert p["state"] == "TX"


def test_provider_detail(client, auth_headers):
    resp = client.get("/api/providers/1234567890", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["npi"] == "1234567890"
    assert "risk_score" in data


def test_provider_detail_not_found(client, auth_headers):
    resp = client.get("/api/providers/0000000000", headers=auth_headers)
    assert resp.status_code == 404


def test_summary_endpoint(client):
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_providers" in data
    assert data["total_providers"] == 3
    assert "total_paid" in data
    assert "flagged_providers" in data


def test_prescan_status(client):
    resp = client.get("/api/prescan/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data or "message" in data
