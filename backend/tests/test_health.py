"""
Tests for health check and readiness endpoints.
"""
import pytest


def test_health_check_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "version" in data


def test_health_check_includes_version(client):
    resp = client.get("/health")
    data = resp.json()
    assert data["version"] == "2.1.5"


def test_readiness_check_returns_structure(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "ready" in data
    assert "checks" in data
    assert isinstance(data["checks"], dict)
    assert "disk" in data["checks"]


def test_readiness_duckdb_check(client):
    """DuckDB check should be present (may be ok or error depending on mock)."""
    resp = client.get("/ready")
    data = resp.json()
    assert "duckdb" in data["checks"]
    assert data["checks"]["duckdb"] in ("ok", "error")


def test_metrics_endpoint_requires_auth(client):
    """Metrics endpoint should return 401 without auth."""
    resp = client.get("/api/admin/metrics")
    assert resp.status_code == 401


def test_metrics_endpoint_returns_data(client, auth_headers):
    """Metrics endpoint should return structured data."""
    resp = client.get("/api/admin/metrics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime_seconds" in data
    assert "total_requests" in data
    assert "endpoints" in data
    assert "scan" in data
    assert "cache" in data


def test_prometheus_metrics(client):
    """Prometheus text endpoint should return text/plain content."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "mfi_uptime_seconds" in resp.text
    assert "mfi_requests_total" in resp.text
