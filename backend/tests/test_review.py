"""
Tests for the review queue CRUD endpoints.
"""
import pytest
from core.review_store import add_to_review_queue, load_review_from_disk
from tests.conftest import SAMPLE_PROVIDERS


@pytest.fixture(autouse=True)
def seed_review_queue():
    """Add flagged providers to the review queue before each test."""
    flagged = [p for p in SAMPLE_PROVIDERS if p.get("risk_score", 0) > 10]
    add_to_review_queue(flagged)
    yield


def test_review_queue_list(client, auth_headers):
    resp = client.get("/api/review", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1


def test_review_queue_filter_by_status(client, auth_headers):
    resp = client.get("/api/review?status=new", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    # All should be 'new' status
    for item in data["items"]:
        assert item.get("status") == "new"


def test_review_counts(client, auth_headers):
    resp = client.get("/api/review/counts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    # Should have at least "new" count
    assert "new" in data or "total" in data


def test_review_update_status(client, auth_headers):
    # Update the first flagged provider
    resp = client.patch(
        "/api/review/1234567890",
        headers=auth_headers,
        json={"status": "investigating"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "investigating"


def test_review_update_not_found(client, auth_headers):
    resp = client.patch(
        "/api/review/0000000000",
        headers=auth_headers,
        json={"status": "investigating"},
    )
    assert resp.status_code == 404


def test_review_add_notes(client, auth_headers):
    resp = client.patch(
        "/api/review/1234567890",
        headers=auth_headers,
        json={"notes": "Suspicious billing pattern observed"},
    )
    assert resp.status_code == 200


def test_review_history(client, auth_headers):
    # First make an update so there's history
    client.patch(
        "/api/review/1234567890",
        headers=auth_headers,
        json={"status": "investigating"},
    )
    resp = client.get("/api/review/1234567890/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "audit_trail" in data
    assert data["npi"] == "1234567890"


def test_review_bulk_update(client, auth_headers):
    resp = client.post(
        "/api/review/bulk-update",
        headers=auth_headers,
        json={"npis": ["1234567890", "5555555555"], "status": "confirmed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "updated" in data
