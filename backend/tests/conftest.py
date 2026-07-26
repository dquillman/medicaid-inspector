"""
Shared fixtures for backend tests.

Hard requirement: tests must NEVER touch real state. The previous version
imported the app directly, so it ran against the developer's live
review_queue.json / users.json — and its `auth_token` fixture *guessed*
passwords ("admin", "password", "test123"), so the whole suite silently
degraded to unauthenticated requests the moment a guess missed (audit
2026-07-25, finding #5).

This conftest instead:
  1. redirects every on-disk state path into a per-run temp directory,
  2. neuters GCS so a run can neither download prod state over local files
     (main.py's lifespan does exactly that) nor upload test junk to the bucket,
  3. seeds a deterministic admin via ADMIN_PASSWORD instead of guessing, and
  4. clears the in-memory rate-limit buckets between tests, so a long run
     doesn't start 429-ing partway through.

All of it happens at MODULE IMPORT time, before `main` (and its lifespan) is
imported by any fixture.
"""
import os
import pathlib
import sys
import tempfile

import pytest

# ── 0. env must be set before anything imports the app ───────────────────────
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# The bootstrap admin (ADMIN_PASSWORD) exists only to create the fixture user.
BOOTSTRAP_USER = "admin"
BOOTSTRAP_PASSWORD = "test-admin-pw-do-not-use-in-prod"
# The identity the tests actually assert on. Admin role: the same fixture is
# used for admin-only endpoints (list/create users, roles).
TEST_ADMIN_USER = "testuser"
TEST_ADMIN_PASSWORD = "testpass123"

os.environ["ADMIN_PASSWORD"] = BOOTSTRAP_PASSWORD    # deterministic bootstrap login
os.environ["GCS_BUCKET"] = ""                        # no bucket => sync no-ops
os.environ["EVIDENCE_ALLOW_LOCAL_ONLY"] = "1"        # evidence tests need no GCS
os.environ.pop("K_SERVICE", None)                    # don't look like Cloud Run
os.environ.pop("TRUSTED_PROXY", None)

# ── 1. redirect all state files into a throwaway directory ───────────────────
_TMP_STATE = pathlib.Path(tempfile.mkdtemp(prefix="mfi-test-state-"))

_STATE_MODULES = [
    "core.review_store", "core.auth_store", "core.evidence_store",
    "core.audit_log", "core.watchlist_store", "core.oig_tips_store",
    "core.referral_workflow", "core.notification_store", "core.roi_store",
    "core.phi_logger", "core.saved_searches", "core.alert_rules",
    "core.store", "core.history_store", "core.lineage",
    "core.database",   # app.db — users/sessions/audit live here too
    "core.perse_store",  # perse_leads.json — read-only, but a test must not read the real sweep
]


def _redirect_state_paths() -> None:
    """Point every module-level Path that lives under the backend dir at the
    temp dir instead. Done by inspection rather than a hand-maintained list of
    filenames, so a newly added store can't quietly start writing real state."""
    import importlib
    for mod_name in _STATE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue  # optional/renamed module — nothing to redirect
        for attr, val in list(vars(mod).items()):
            if not isinstance(val, pathlib.Path):
                continue
            try:
                rel = val.resolve().relative_to(_BACKEND_DIR)
            except (ValueError, OSError):
                continue  # not backend-relative — leave it alone
            new = _TMP_STATE / rel
            new.parent.mkdir(parents=True, exist_ok=True)
            setattr(mod, attr, new)


def _neuter_gcs() -> None:
    """A test run must not download prod state over local files, nor upload
    test data to the bucket."""
    try:
        from core import gcs_sync
    except Exception:
        return
    gcs_sync.download_state_files = lambda *a, **k: 0
    gcs_sync.download_all = lambda *a, **k: 0
    gcs_sync.download_parquet = lambda *a, **k: False
    gcs_sync.download_prescan_cache = lambda *a, **k: False
    gcs_sync.upload_file = lambda *a, **k: False
    gcs_sync.upload_all = lambda *a, **k: 0
    gcs_sync.upload_bytes = lambda *a, **k: False
    gcs_sync.download_bytes = lambda *a, **k: None


_redirect_state_paths()
_neuter_gcs()


# ── 2. deterministic sample data ─────────────────────────────────────────────
# Referenced by test_review.py — its absence was a hard collection error that
# took the ENTIRE suite down (pytest exits on collection error).
SAMPLE_PROVIDERS: list[dict] = [
    # Shape is dictated by the existing tests (they were written against this
    # fixture before it went missing): NPI 1234567890 is "Test Provider A",
    # exactly TWO are in TX, and A carries risk 65 so the watchlist-alert test
    # (threshold 50) trips. Change these values and those tests change meaning.
    {
        "npi": "1234567890", "provider_name": "Test Provider A",
        "state": "TX", "specialty": "Psychiatry Physician",
        "risk_score": 65.0, "total_paid": 4_200_000.0, "total_claims": 9_100,
        "total_beneficiaries": 260, "first_month": "2023-01", "last_month": "2024-10",
        "top_hcpcs": "H0046", "distinct_hcpcs": 3, "flag_count": 2,
        # flags = the FLAGGED subset of signal_results (dicts), matching what
        # scan_engine actually emits — not a list of signal-name strings.
        "flags": [
            {"signal": "revenue_per_bene_outlier", "flagged": True, "score": 0.93, "weight": 15},
            {"signal": "billing_concentration", "flagged": True, "score": 0.88, "weight": 10},
        ],
        "signal_results": [
            {"signal": "revenue_per_bene_outlier", "flagged": True, "score": 0.93,
             "weight": 15, "reason": "Revenue/beneficiary is 9.4 sigma above peers"},
            {"signal": "billing_concentration", "flagged": True, "score": 0.88,
             "weight": 10, "reason": "H0046 is 100% of billing"},
        ],
    },
    {
        "npi": "1234567891", "provider_name": "Test Provider B",
        "state": "TX", "specialty": "Durable Medical Equipment & Medical Supplies",
        "risk_score": 41.0, "total_paid": 900_000.0, "total_claims": 3_400,
        "total_beneficiaries": 410, "first_month": "2022-06", "last_month": "2024-06",
        "top_hcpcs": "E0601", "distinct_hcpcs": 12, "flag_count": 1,
        "flags": [{"signal": "claims_per_bene_anomaly", "flagged": True, "score": 0.61, "weight": 10}],
        "signal_results": [
            {"signal": "claims_per_bene_anomaly", "flagged": True, "score": 0.61,
             "weight": 10, "reason": "8.3 claims/beneficiary vs peer mean 3.1"},
        ],
    },
    {
        "npi": "1234567892", "provider_name": "Test Provider C",
        "state": "OR", "specialty": "Internal Medicine Physician",
        "risk_score": 4.0, "total_paid": 120_000.0, "total_claims": 800,
        "total_beneficiaries": 300, "first_month": "2021-01", "last_month": "2024-09",
        "top_hcpcs": "99213", "distinct_hcpcs": 40, "flag_count": 0,
        "flags": [], "signal_results": [],
    },
]


# ── 3. fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """TestClient bound to the real app, but against isolated state, with a
    DETERMINISTIC provider cache.

    The app's lifespan loads whatever prescan cache happens to exist on the
    developer's machine, so provider/review/watchlist assertions depended on
    local data and drifted (they were asserting 3 providers against a cache
    holding 1). Overwriting the store with SAMPLE_PROVIDERS after startup makes
    every run identical regardless of what's on disk."""
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        from core.store import set_prescanned
        set_prescanned(list(SAMPLE_PROVIDERS))
        # Seed the fixture identity the tests assert on.
        boot = c.post("/api/auth/login",
                      json={"username": BOOTSTRAP_USER, "password": BOOTSTRAP_PASSWORD})
        assert boot.status_code == 200, f"bootstrap admin login failed: {boot.text}"
        c.post("/api/auth/users",
               headers={"Authorization": f"Bearer {boot.json()['token']}"},
               json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD,
                     "role": "admin", "display_name": "Test User"})
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    """Real admin token. Asserts loudly rather than silently degrading to
    unauthenticated requests the way the old password-guessing fixture did."""
    resp = client.post("/api/auth/login",
                       json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD})
    assert resp.status_code == 200, (
        f"Test admin login failed ({resp.status_code}): {resp.text}. "
        "conftest sets ADMIN_PASSWORD before the app is imported — if this fails, "
        "the auth bootstrap changed."
    )
    return resp.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def throwaway_headers(client):
    """A FRESH, function-scoped token for tests that destroy their own session
    (logout, revocation). Using the session-scoped `auth_headers` for that
    invalidates the shared token and 401s every later test — which is exactly
    what test_logout used to do."""
    resp = client.post("/api/auth/login",
                       json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD})
    assert resp.status_code == 200, f"throwaway login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(autouse=True)
def _reset_watchlist():
    """Empty the watchlist before each test. It is process-global state, so
    without this an entry added by one test leaks into the next (test_check_watched
    asserted 'not watched' on an NPI a previous test had already added)."""
    try:
        from core import watchlist_store
        watchlist_store._watchlist_items.clear()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Clear rate-limit buckets before every test. The suite makes far more than
    100 requests/minute from one IP, so without this a long run starts returning
    429 partway through and tests fail for the wrong reason."""
    try:
        from core import rate_limiter
        for name in ("_api_buckets", "_login_buckets"):
            bucket = getattr(rate_limiter, name, None)
            if bucket is not None:
                bucket.clear()
    except Exception:
        pass
    yield


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_state():
    yield
    import shutil
    shutil.rmtree(_TMP_STATE, ignore_errors=True)
