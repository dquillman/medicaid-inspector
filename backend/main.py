"""
Medicaid Fraud Detection Dashboard — FastAPI backend.
Run with: uvicorn main:app --reload --port 8000
"""
import asyncio
import logging
import os
import time as _time_mod
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime
import re

from routes.auth import require_user, require_admin
from core.rate_limiter import RateLimitMiddleware, check_login_rate

from core.config import settings


def _validate_state_filter(state: Optional[str]) -> Optional[str]:
    """Whitelist validation for state codes — only allow 2-letter uppercase codes."""
    if state is None:
        return None
    state = state.strip().upper()
    if not re.match(r'^[A-Z]{2}$', state):
        raise HTTPException(400, f"Invalid state filter '{state}' — must be a 2-letter state code")
    return state
from core.store import (
    set_prescanned, get_prescanned,
    append_prescanned, reset_scan,
    set_prescan_status, get_prescan_status,
    load_prescanned_from_disk,
    get_scan_progress, set_scan_progress,
)
from data.duckdb_client import (
    get_connection, query_async,
    provider_aggregate_sql, count_providers_sql,
    detect_state_column, get_parquet_path,
)
from routes import providers, anomalies, states, network, review, auth, billing
from routes import alerts, cases, audit, ownership, roi, exclusions, geography
from routes import demographics, hotspots, beneficiary, utilization, population, trends
from routes import timeline, temporal
from routes import related
from routes import watchlist
from routes import rings
from routes import specialty
from routes import score_trends
from routes import medicare
from routes import news
from routes import referral
from routes import license
from routes import data_pipeline
from routes import beneficiary_fraud
from routes import ml as ml_routes
from routes import pharmacy_dme
from routes import notifications
from routes import saved_searches
from routes import claim_patterns
from routes import integrations
from routes import tasks as tasks_route
from routes import retention as retention_routes
from routes import evidence as evidence_routes
from routes import mfcu_referral
from routes import backup as backup_routes
from routes import phi_admin
from routes import billing_codes
from core.metrics import record_request, get_metrics, get_prometheus_text
from core.phi_middleware import PHIAccessMiddleware
from core.phi_logger import load_phi_log_from_disk, log_phi_access, PHI_PATH_PATTERNS
from core.evidence_store import load_evidence_from_disk
from core.referral_workflow import load_referrals_from_disk
from core.notification_store import load_notifications_from_disk
from core.saved_search_store import load_saved_searches_from_disk
from core.news_store import load_news_from_disk
from core.review_store import load_review_from_disk
from core.oig_store import load_oig_from_disk, download_oig_list
from core.enrollment_store import load_or_fetch_enrollment
from core.alert_store import load_rules_from_disk
from core.audit_log import load_audit_from_disk
from core.roi_store import load_roi_from_disk
from core.auth_store import init_auth_store
from core.score_history import load_history_from_disk, record_batch_snapshots
from core.watchlist_store import load_watchlist_from_disk
from core.lineage_store import load_lineage_from_disk, record_scan_run
from core.scan_lock import acquire_scan_lock, release_scan_lock, is_scan_running
from core.task_queue import enqueue_task
from core.database import init_db, migrate_users_from_json
from services.data_discovery import load_dataset_config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Scan engine — extracted to services/scan_engine.py
from services.scan_engine import (
    run_scan_batch as _run_scan_batch,
    rescore_cached_providers as _rescore_cached,
    get_scan_state,
    is_scan_active,
    stop_auto_mode,
    start_batch_scan,
    start_auto_scan,
    start_smart_scan,
)


def _finish_prescan_load():
    """Post-load bookkeeping after prescan_cache.json is available in memory."""
    prog = get_scan_progress()
    scanned = prog.get("offset", 0)
    total = prog.get("total_provider_count")
    msg = f"Loaded {len(get_prescanned())} providers from cache"
    if total:
        msg += f" · {scanned:,} of {total:,} scanned"
    set_prescan_status(0, msg)
    log.info(msg)

    # Enrich providers missing NPPES data
    missing_nppes = [
        p["npi"] for p in get_prescanned()
        if not p.get("nppes") or not (p.get("nppes") or {}).get("enumeration_date")
    ]
    if missing_nppes:
        from services.nppes_enricher import enrich_batch_with_nppes
        from core.cache import invalidate_nppes_cache
        invalidate_nppes_cache()
        asyncio.get_event_loop().create_task(enrich_batch_with_nppes(missing_nppes))
        log.info("Queued NPPES enrichment for %d providers", len(missing_nppes))


async def _bg_download_and_load_prescan():
    """Background: download prescan_cache.json from GCS then load into memory."""
    from core.gcs_sync import download_prescan_cache_async
    ok = await download_prescan_cache_async()
    if ok and load_prescanned_from_disk():
        _finish_prescan_load()
    else:
        set_prescan_status(0, "Idle — use the Scan button to begin")
        log.info("No prescan cache in GCS — idle.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── GCS: restore small state files before init (skip large Parquet) ──
    from core.gcs_sync import download_state_files as _gcs_download_state
    state_count = await asyncio.to_thread(_gcs_download_state)
    if state_count:
        log.info("Restored %d state files from GCS bucket", state_count)

    log.info("Initializing DuckDB with httpfs…")
    await asyncio.to_thread(get_connection)
    log.info("DuckDB ready.")

    # Initialize SQLite database for critical app state
    init_db()
    import pathlib as _pl
    _users_json = _pl.Path(__file__).parent / "users.json"
    migrate_users_from_json(_users_json)

    await asyncio.gather(
        asyncio.to_thread(load_review_from_disk),
        asyncio.to_thread(load_rules_from_disk),
        asyncio.to_thread(load_audit_from_disk),
        asyncio.to_thread(load_roi_from_disk),
        asyncio.to_thread(load_watchlist_from_disk),
        asyncio.to_thread(load_history_from_disk),
        asyncio.to_thread(load_news_from_disk),
        asyncio.to_thread(load_lineage_from_disk),
        asyncio.to_thread(load_dataset_config),
        asyncio.to_thread(load_notifications_from_disk),
        asyncio.to_thread(load_saved_searches_from_disk),
        asyncio.to_thread(load_phi_log_from_disk),
        asyncio.to_thread(load_evidence_from_disk),
        asyncio.to_thread(load_referrals_from_disk),
        asyncio.to_thread(init_auth_store),
    )

    # Load OIG exclusion list — try cache first, download if missing
    if not load_oig_from_disk():
        asyncio.create_task(download_oig_list())

    # Load Medicaid enrollment data (disk cache or CMS API)
    asyncio.create_task(load_or_fetch_enrollment())

    # Try loading prescan from local disk first (works on dev machine)
    if load_prescanned_from_disk():
        _finish_prescan_load()
    else:
        # On Cloud Run, prescan_cache.json isn't on disk yet — download from GCS in background
        set_prescan_status(0, "Loading scan data from cloud storage…")
        log.info("No local cache — will try GCS download in background")
        asyncio.create_task(_bg_download_and_load_prescan())

    # NOTE: Parquet stays remote (read via DuckDB httpfs) — no local download on Cloud Run.
    # The 2.8GB file is too large to download reliably in a container.

    yield


app = FastAPI(
    title="Medicaid Fraud Detection API",
    description="Streams provider-level Medicaid claims from remote Parquet via DuckDB httpfs.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5200",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8001",
        # Production origins (Firebase Hosting)
        "https://medicaid-inspector.web.app",
        "https://medicaid-inspector.firebaseapp.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Rate limiting middleware — must be added after CORS middleware
app.add_middleware(RateLimitMiddleware)


# ── Security headers middleware ──────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# Routers sharing /api/providers prefix with specific sub-paths must come
# BEFORE the main providers router (which has a /{npi} catch-all).
app.include_router(referral.router)
app.include_router(timeline.router)
app.include_router(related.router)
app.include_router(medicare.router)
app.include_router(license.router)
app.include_router(news.provider_news_router)
app.include_router(providers.router)
app.include_router(anomalies.router)
app.include_router(states.router)
app.include_router(network.router)
app.include_router(review.router)
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(alerts.router)
app.include_router(cases.router)
app.include_router(audit.router)
app.include_router(ownership.router)
app.include_router(roi.router)
app.include_router(exclusions.router)
app.include_router(geography.router)
app.include_router(demographics.router)
app.include_router(hotspots.router)
app.include_router(beneficiary.router)
app.include_router(utilization.router)
app.include_router(population.router)
app.include_router(trends.router)
app.include_router(temporal.router)
app.include_router(watchlist.router)
app.include_router(specialty.router)
app.include_router(rings.router)
app.include_router(score_trends.router)
app.include_router(news.router)
app.include_router(beneficiary_fraud.router)
app.include_router(ml_routes.router)
app.include_router(pharmacy_dme.router)
app.include_router(data_pipeline.router)
app.include_router(notifications.router)
app.include_router(saved_searches.router)
app.include_router(claim_patterns.router)
app.include_router(integrations.router)
app.include_router(integrations.admin_router)
app.include_router(integrations.provider_router)
app.include_router(tasks_route.router)
app.include_router(retention_routes.router)
app.include_router(evidence_routes.router)
app.include_router(mfcu_referral.router)
app.include_router(backup_routes.router)
app.include_router(billing_codes.router)
app.include_router(phi_admin.router)
app.add_middleware(PHIAccessMiddleware)


# ── Request timing middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = _time_mod.time()
    response = await call_next(request)
    duration = _time_mod.time() - start
    path = request.url.path
    record_request(path, request.method, response.status_code, duration)
    return response


# ── Scan control endpoints ────────────────────────────────────────────────────

class ScanBatchRequest(BaseModel):
    batch_size: int = settings.SCAN_BATCH_SIZE
    state_filter: Optional[str] = None
    force: bool = False  # When True, skip incremental check and rescan all providers


@app.post("/api/prescan/scan-batch", dependencies=[Depends(require_user)])
async def trigger_scan_batch(body: ScanBatchRequest = None):
    if body is None:
        body = ScanBatchRequest()
    body.state_filter = _validate_state_filter(body.state_filter)
    if is_scan_active():
        raise HTTPException(409, "A scan is already in progress")
    try:
        task_id = start_batch_scan(body.batch_size, body.state_filter or None, body.force)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"started": True, "batch_size": body.batch_size, "state_filter": body.state_filter, "force": body.force, "task_id": task_id}


@app.post("/api/prescan/auto-start", dependencies=[Depends(require_user)])
async def auto_start_scan(body: ScanBatchRequest = None):
    if body is None:
        body = ScanBatchRequest()
    body.state_filter = _validate_state_filter(body.state_filter)
    task_id = start_auto_scan(body.batch_size, body.state_filter or None, body.force)
    if not task_id:
        return {"started": False, "auto_mode": True, "note": "Auto mode enabled — will continue after current batch"}
    return {"started": True, "auto_mode": True, "batch_size": body.batch_size}


@app.post("/api/prescan/auto-stop", dependencies=[Depends(require_user)])
async def auto_stop_scan():
    stop_auto_mode()
    return {"auto_mode": False, "note": "Auto mode disabled — current batch will finish normally"}


@app.post("/api/prescan/rescore", dependencies=[Depends(require_user)])
async def rescore_endpoint():
    """Re-run all fraud signals against cached providers."""
    return await _rescore_cached()


class SmartScanRequest(BaseModel):
    state_filter: Optional[str] = None


@app.post("/api/prescan/smart-scan", dependencies=[Depends(require_user)])
async def smart_scan_endpoint(body: SmartScanRequest = None):
    """High-risk-first scan (requires local Parquet data)."""
    if not is_local():
        raise HTTPException(400, "Smart scan requires the local dataset — download it first via the Data Source card.")
    if is_scan_active():
        raise HTTPException(409, "A scan is already in progress")
    state = _validate_state_filter(body.state_filter if body else None)
    try:
        task_id = start_smart_scan(state or None)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"started": True, "mode": "smart", "task_id": task_id}


@app.post("/api/prescan/reset", dependencies=[Depends(require_admin)])
async def reset_scan_endpoint():
    if is_scan_active():
        raise HTTPException(409, "Cannot reset while a scan is in progress")
    stop_auto_mode()
    reset_scan()
    set_prescan_status(0, "Idle — scan has been reset")
    return {"ok": True}


# ── Summary + status ──────────────────────────────────────────────────────────

@app.get("/api/summary", dependencies=[Depends(require_user)])
async def summary():
    """
    Instant KPIs from prescan cache. No DuckDB queries on this endpoint.
    """
    prescanned: list[dict] = get_prescanned()

    if not prescanned:
        return {
            "total_providers": 0,
            "total_paid": 0,
            "total_claims": 0,
            "total_beneficiaries": 0,
            "flagged_providers": 0,
            "high_risk_providers": 0,
            "avg_risk_score": 0.0,
            "prescan_complete": False,
            "note": "No providers scanned yet — use the Scan button to begin.",
        }

    total_paid = sum(p.get("total_paid") or 0 for p in prescanned)
    total_claims = sum(p.get("total_claims") or 0 for p in prescanned)
    total_bene = sum(p.get("total_beneficiaries") or 0 for p in prescanned)
    flagged    = sum(1 for p in prescanned if p.get("risk_score", 0) > settings.RISK_THRESHOLD)
    high_risk  = sum(1 for p in prescanned if p.get("risk_score", 0) >= 50)
    avg_risk = sum(p.get("risk_score", 0) for p in prescanned) / len(prescanned)

    prog = get_scan_progress()
    total_providers = prog.get("total_provider_count")
    note = f"{len(prescanned):,} providers scanned"
    if total_providers:
        note += f" of {total_providers:,} total"

    return {
        "total_providers": len(prescanned),
        "total_paid": total_paid,
        "total_claims": total_claims,
        "total_beneficiaries": total_bene,
        "flagged_providers": flagged,
        "high_risk_providers": high_risk,
        "avg_risk_score": round(avg_risk, 1),
        "prescan_complete": True,
        "note": note,
    }


@app.get("/api/prescan/status", dependencies=[Depends(require_user)])
async def prescan_status_endpoint():
    status = get_prescan_status()
    status.update(get_scan_state())
    return status


@app.post("/api/ml/train", dependencies=[Depends(require_user)])
async def train_ml_model():
    """Train Isolation Forest on all cached providers and return anomaly scores."""
    from services.ml_scorer import train_and_score
    try:
        result = train_and_score()
        return result
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.get("/api/ml/status", dependencies=[Depends(require_user)])
async def ml_status():
    """Return ML model training status and stats."""
    from services.ml_scorer import get_ml_status
    return get_ml_status()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat(), "version": "2.1.5"}


@app.get("/ready")
async def readiness_check():
    """Check DuckDB connection, disk space, etc."""
    checks = {}
    try:
        from data.duckdb_client import get_connection
        get_connection()
        checks["duckdb"] = "ok"
    except Exception:
        checks["duckdb"] = "error"
    checks["disk"] = "ok"
    all_ok = all(v == "ok" for v in checks.values())
    return {"ready": all_ok, "checks": checks}


@app.get("/api/admin/metrics")
async def admin_metrics(user: dict = Depends(require_admin)):
    """JSON metrics dashboard — request counts, timing, scan stats, cache hit rates."""
    return get_metrics()


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus-compatible text format metrics."""
    return get_prometheus_text()


# ── Local data download ───────────────────────────────────────────────────────

import pathlib as _pathlib
import httpx as _httpx
from data.duckdb_client import _LOCAL_PARQUET, is_local, get_parquet_path, get_local_path
from core.cache import invalidate_query_cache

_download_state: dict = {"active": False, "bytes_done": 0, "bytes_total": 0, "done": False, "error": None}


async def _do_download():
    global _download_state
    _download_state = {"active": True, "bytes_done": 0, "bytes_total": 0, "done": False, "error": None}
    _LOCAL_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    tmp = _LOCAL_PARQUET.with_suffix(".parquet.tmp")
    try:
        async with _httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", settings.PARQUET_URL) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                _download_state["bytes_total"] = total
                with open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1_048_576):
                        f.write(chunk)
                        _download_state["bytes_done"] += len(chunk)
        tmp.rename(_LOCAL_PARQUET)
        invalidate_query_cache()
        _download_state["done"] = True
        _download_state["active"] = False
        log.info("Dataset downloaded to %s — switching to local mode", _LOCAL_PARQUET)
    except Exception as e:
        log.error("Download failed: %s", e)
        _download_state["error"] = str(e)
        _download_state["active"] = False
        if tmp.exists():
            tmp.unlink()


@app.get("/api/data/status", dependencies=[Depends(require_user)])
async def data_status():
    """Report whether the dataset is local or remote, and download progress if active."""
    dl = _download_state
    pct = 0
    if dl["bytes_total"] > 0:
        pct = round(dl["bytes_done"] / dl["bytes_total"] * 100, 1)
    resolved = get_local_path()
    return {
        "is_local":        is_local(),
        "local_path":      str(resolved) if is_local() else None,
        "expected_path":   str(resolved),   # always shown so user knows where to put the file
        "remote_url":      settings.PARQUET_URL,
        "file_size_gb":    round(resolved.stat().st_size / 1_073_741_824, 2) if is_local() else 2.74,
        "download": {
            "active":      dl["active"],
            "bytes_done":  dl["bytes_done"],
            "bytes_total": dl["bytes_total"],
            "pct":         pct,
            "done":        dl["done"],
            "error":       dl["error"],
        },
    }


@app.post("/api/data/download", dependencies=[Depends(require_admin)])
async def start_download():
    """Start downloading the dataset to local disk (runs in background)."""
    if is_local():
        return {"ok": False, "message": "Dataset already downloaded locally"}
    if _download_state["active"]:
        return {"ok": False, "message": "Download already in progress"}
    asyncio.create_task(_do_download())
    return {"ok": True, "message": "Download started"}


# ── Serve frontend static files (production) ─────────────────────────────────
_static_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist"))
log.info("Static dir: %s (exists=%s)", _static_dir, os.path.isdir(_static_dir))
if os.path.isdir(_static_dir):
    # Serve static assets (JS, CSS, etc.)
    app.mount("/assets", StaticFiles(directory=os.path.join(_static_dir, "assets")), name="static-assets")

    # Catch-all for SPA routing — must be last
    @app.get("/", include_in_schema=False)
    async def serve_spa_root():
        return FileResponse(os.path.join(_static_dir, "index.html"))

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str):
        file_path = os.path.join(_static_dir, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_static_dir, "index.html"))
