"""
Shared test fixtures for the Medicaid Inspector backend test suite.
Provides a FastAPI TestClient with mocked DuckDB and pre-seeded data stores.
"""
import json
import sys
import pathlib
import pytest
from unittest.mock import patch, MagicMock

# Ensure the backend directory is importable
_backend_dir = pathlib.Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))


# ── Mock DuckDB before any app imports ────────────────────────────────────────

_mock_conn = MagicMock()
_mock_conn.execute.return_value = _mock_conn
_mock_conn.fetchall.return_value = []
_mock_conn.fetchone.return_value = None
_mock_conn.description = []


@pytest.fixture(autouse=True)
def mock_duckdb():
    """Patch DuckDB so tests never touch real data."""
    with patch("data.duckdb_client.get_connection", return_value=_mock_conn), \
         patch("data.duckdb_client.query_async", return_value=[]), \
         patch("data.duckdb_client.is_local", return_value=False):
        yield _mock_conn


# ── Sample provider data ──────────────────────────────────────────────────────

SAMPLE_PROVIDERS = [
    {
        "npi": "1234567890",
        "provider_name": "Test Provider A",
        "state": "TX",
        "city": "Houston",
        "specialty": "Internal Medicine",
        "total_paid": 500000.0,
        "total_claims": 1200,
        "total_beneficiaries": 300,
        "revenue_per_beneficiary": 1666.67,
        "claims_per_beneficiary": 4.0,
        "risk_score": 65.0,
        "flags": [{"signal": "billing_concentration", "flagged": True, "score": 8, "weight": 1}],
        "signal_results": [],
        "hcpcs": [{"hcpcs_code": "99213", "total_paid": 200000, "claim_count": 600}],
        "timeline": [],
        "top_hcpcs": "99213",
        "nppes": {"name": "Test Provider A", "address": {"state": "TX", "city": "Houston"}},
    },
    {
        "npi": "9876543210",
        "provider_name": "Test Provider B",
        "state": "CA",
        "city": "Los Angeles",
        "specialty": "Family Medicine",
        "total_paid": 150000.0,
        "total_claims": 400,
        "total_beneficiaries": 100,
        "revenue_per_beneficiary": 1500.0,
        "claims_per_beneficiary": 4.0,
        "risk_score": 5.0,
        "flags": [],
        "signal_results": [],
        "hcpcs": [{"hcpcs_code": "99214", "total_paid": 100000, "claim_count": 300}],
        "timeline": [],
        "top_hcpcs": "99214",
        "nppes": {"name": "Test Provider B", "address": {"state": "CA", "city": "Los Angeles"}},
    },
    {
        "npi": "5555555555",
        "provider_name": "Test Provider C",
        "state": "TX",
        "city": "Dallas",
        "specialty": "Internal Medicine",
        "total_paid": 2000000.0,
        "total_claims": 5000,
        "total_beneficiaries": 200,
        "revenue_per_beneficiary": 10000.0,
        "claims_per_beneficiary": 25.0,
        "risk_score": 85.0,
        "flags": [
            {"signal": "billing_concentration", "flagged": True, "score": 8, "weight": 1},
            {"signal": "revenue_per_bene_outlier", "flagged": True, "score": 10, "weight": 1},
        ],
        "signal_results": [],
        "hcpcs": [],
        "timeline": [],
        "top_hcpcs": "99213",
        "nppes": {"name": "Test Provider C", "address": {"state": "TX", "city": "Dallas"}},
    },
]


@pytest.fixture(autouse=True)
def seed_prescan_cache():
    """Pre-seed the in-memory prescan cache with sample providers."""
    from core.store import set_prescanned, set_scan_progress
    set_prescanned(list(SAMPLE_PROVIDERS))
    set_scan_progress(3, 3, None, 1)
    yield
    set_prescanned([])


@pytest.fixture(autouse=True)
def mock_auth_store(tmp_path):
    """Initialize auth store with a temp users file and seed a test user."""
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({}))
    with patch("core.auth_store._USERS_FILE", users_file):
        from core.auth_store import init_auth_store, create_user, create_session
        init_auth_store()
        # Create a test user
        create_user(username="testuser", password="testpass123", role="admin", display_name="Test User")
        yield


@pytest.fixture()
def auth_token():
    """Return a valid session token for the test user."""
    from core.auth_store import create_session
    return create_session("testuser")


@pytest.fixture()
def auth_headers(auth_token):
    """Return headers dict with Authorization Bearer token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture()
def client():
    """FastAPI TestClient (no lifespan — stores are already seeded via fixtures)."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app, raise_server_exceptions=False)
