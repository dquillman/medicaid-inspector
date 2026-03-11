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
from core.metrics import record_request, get_metrics, get_prometheus_text
from core.phi_middleware import PHIAccessMiddleware
from core.phi_logger import load_phi_log_from_disk, log_phi_access, PHI_PATH_PATTERNS
from core.evidence_store import load_evidence_from_disk
from core.referral_workflow import load_referrals_from_disk
from core.notification_store import load_notifications_from_disk
from core.saved_search_store import load_saved_searches_from_disk
from core.news_store import load_news_from_disk
from core.review_store import load_review_from_disk, add_to_review_queue
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

# Prevents two scan batches from running simultaneously
# TODO: _scan_running/_auto_mode globals are per-process; broken under multi-worker
_scan_running = False
_auto_mode = False
_smart_scan_mode = False


async def _run_scan_batch(batch_size: int, state_filter: Optional[str], force: bool = False):
    """
    Scans the next `batch_size` providers from the Parquet file.
    Appends results to the disk cache and updates scan progress.
    Runs as a background task — HTTP response is returned immediately.
    """
    global _scan_running, _auto_mode
    _hand_off = False  # True when auto mode passes ownership to next task

    from services.anomaly_detector import (
        billing_concentration,
        revenue_per_bene_outlier,
        claims_per_bene_anomaly,
        billing_ramp_rate,
        bust_out_pattern,
        ghost_billing,
        total_spend_outlier,
        billing_consistency,
        bene_concentration,
        upcoding_pattern,
        address_cluster_risk,
        oig_excluded,
        compute_address_clusters,
        specialty_mismatch,
        corporate_shell_risk,
        compute_auth_official_clusters,
        dead_npi_billing,
        new_provider_explosion,
        geographic_impossibility,
    )
    import statistics as _stats
    from collections import defaultdict as _dd

    try:
        _scan_start_time = _time_mod.time()

        # Run data validation at scan startup (first batch only)
        progress = get_scan_progress()
        if progress.get("offset", 0) == 0:
            try:
                from services.data_validator import run_validation
                set_prescan_status(1, "Running data quality validation…")
                await run_validation(sample_limit=2000)
                log.info("Pre-scan data validation complete")
            except Exception as val_err:
                log.warning("Data validation failed (non-fatal): %s", val_err)

        # If caller provides a different state filter, start offset over
        active_filter = state_filter or progress.get("state_filter")
        if state_filter and state_filter != progress.get("state_filter") and progress.get("offset", 0) > 0:
            log.info("State filter changed (%s → %s) — resetting offset", progress.get("state_filter"), state_filter)
            progress = {"offset": 0, "total_provider_count": None, "state_filter": state_filter, "batches_completed": 0, "last_batch_at": None}

        offset = progress.get("offset", 0)
        total = progress.get("total_provider_count")
        batches = progress.get("batches_completed", 0)

        # Build WHERE clause for state filter (parameterized)
        state_where = ""
        state_params: tuple = ()
        if active_filter:
            state_col = await asyncio.to_thread(detect_state_column)
            if state_col:
                state_where = f"{state_col} = ?"
                state_params = (active_filter,)
            else:
                log.warning("State column not found in Parquet — state filter ignored")
                active_filter = None

        # ── Count total providers (first batch only) ──────────────────────────
        if total is None:
            label = f" in {active_filter}" if active_filter else ""
            set_prescan_status(1, f"Counting total providers{label}…")
            log.info("Counting distinct providers%s…", label)
            count_rows = await query_async(count_providers_sql(where=state_where), state_params)
            total = int(count_rows[0]["total"]) if count_rows else 0
            log.info("Total providers: %d", total)

        if total == 0:
            set_prescan_status(0, "No providers found")
            return

        # ── Step 1: provider aggregates ───────────────────────────────────────
        set_prescan_status(2, f"Fetching provider aggregates (offset {offset:,} of {total:,})…")
        log.info("Scan batch: offset=%d, batch_size=%d, state=%s", offset, batch_size, active_filter)
        agg_rows = await query_async(
            provider_aggregate_sql(where=state_where, limit=batch_size, offset=offset),
            state_params,
        )

        if not agg_rows:
            set_prescan_status(0, f"Scan complete — all {offset:,} providers checked")
            set_scan_progress(offset, total, active_filter, batches)
            log.info("Scan complete at offset %d", offset)
            return

        # ── Single pass over prescan cache: build already_scanned + peer stats ──
        already_scanned: set[str] = set()
        peer_rpb: dict[str, list[float]] = _dd(list)
        peer_cpb: dict[str, list[float]] = _dd(list)
        all_spend: list[float] = []
        for cached in get_prescanned():
            already_scanned.add(cached["npi"])
            c_code = cached.get("top_hcpcs") or ""
            if not c_code:
                hcpcs_list = cached.get("hcpcs") or []
                if hcpcs_list:
                    c_code = hcpcs_list[0].get("hcpcs_code", "")
            c_rpb = cached.get("revenue_per_beneficiary") or 0.0
            if c_code and c_rpb > 0:
                peer_rpb[c_code].append(float(c_rpb))
            cpb = cached.get("claims_per_beneficiary") or 0
            if c_code and cpb > 0:
                peer_cpb[c_code].append(float(cpb))
            spend = cached.get("total_paid") or 0
            if spend > 0:
                all_spend.append(float(spend))

        # ── Incremental loading (#10): skip already-scanned NPIs unless force=True
        if not force:
            new_rows = [r for r in agg_rows if r["npi"] not in already_scanned]
            if new_rows and len(new_rows) < len(agg_rows):
                skipped = len(agg_rows) - len(new_rows)
                log.info("Incremental: skipped %d already-scanned providers, %d new", skipped, len(new_rows))
            if not new_rows:
                # All providers in this batch already scanned — advance offset and continue
                new_offset = offset + len(agg_rows)
                set_scan_progress(new_offset, total, active_filter, batches + 1)
                log.info("Incremental: entire batch already scanned — advancing offset to %d", new_offset)
                remaining = total - new_offset
                set_prescan_status(
                    0,
                    f"Idle — {new_offset:,} of {total:,} providers scanned"
                    + (f" · {remaining:,} remaining" if remaining > 0 else " · Complete"),
                )
                if _auto_mode and len(agg_rows) == batch_size:
                    await asyncio.sleep(0.2)
                    asyncio.create_task(_run_scan_batch(batch_size, active_filter, force=False))
                    return
                return
            agg_rows = new_rows

        npi_list = [r["npi"] for r in agg_rows]
        npi_placeholders = ", ".join("?" for _ in npi_list)
        npi_params = tuple(npi_list)

        # ── Step 2: batch HCPCS ────────────────────────────────────────────────
        set_prescan_status(2, f"Fetching HCPCS breakdown for {len(npi_list)} providers…")
        hcpcs_sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM    AS npi,
            HCPCS_CODE                  AS hcpcs_code,
            SUM(TOTAL_PAID)             AS total_paid,
            SUM(TOTAL_CLAIMS)           AS total_claims
        FROM read_parquet('{get_parquet_path()}')
        WHERE BILLING_PROVIDER_NPI_NUM IN ({npi_placeholders})
        GROUP BY npi, hcpcs_code
        ORDER BY npi, total_paid DESC
        """
        hcpcs_rows = await query_async(hcpcs_sql, npi_params)
        hcpcs_by_npi: dict[str, list[dict]] = {}
        for r in hcpcs_rows:
            hcpcs_by_npi.setdefault(r["npi"], []).append(r)

        # ── Step 3: batch timelines ────────────────────────────────────────────
        set_prescan_status(3, f"Fetching monthly timelines for {len(npi_list)} providers…")
        timeline_sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM            AS npi,
            CLAIM_FROM_MONTH                    AS month,
            SUM(TOTAL_PAID)                     AS total_paid,
            SUM(TOTAL_CLAIMS)                   AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS total_unique_beneficiaries
        FROM read_parquet('{get_parquet_path()}')
        WHERE BILLING_PROVIDER_NPI_NUM IN ({npi_placeholders})
        GROUP BY npi, month
        ORDER BY npi, month ASC
        """
        timeline_rows = await query_async(timeline_sql, npi_params)
        timeline_by_npi: dict[str, list[dict]] = {}
        for r in timeline_rows:
            timeline_by_npi.setdefault(r["npi"], []).append(r)

        # ── Step 4: score in Python ────────────────────────────────────────────
        set_prescan_status(3, f"Scoring {len(npi_list)} providers…")

        top_hcpcs_by_npi: dict[str, str] = {
            npi: rows[0]["hcpcs_code"]
            for npi, rows in hcpcs_by_npi.items() if rows
        }

        # Add current batch to peer stats (cache-seeded above in single pass)
        for row in agg_rows:
            code = top_hcpcs_by_npi.get(row["npi"])
            rpb = row.get("revenue_per_beneficiary") or 0.0
            if code and rpb > 0:
                peer_rpb[code].append(float(rpb))
            cpb = row.get("claims_per_beneficiary") or 0
            if code and cpb > 0:
                peer_cpb[code].append(float(cpb))
            spend = row.get("total_paid") or 0
            if spend > 0:
                all_spend.append(float(spend))
            # Store top_hcpcs in the result for future batches
            if code:
                row["top_hcpcs"] = code

        peer_stats: dict[str, tuple[float, float]] = {}
        for code, vals in peer_rpb.items():
            if len(vals) >= 3:
                m = _stats.mean(vals)
                s = _stats.stdev(vals) if len(vals) > 1 else 0.0
                peer_stats[code] = (m, s)

        cpb_stats: dict[str, tuple[float, float]] = {}
        for code, vals in peer_cpb.items():
            if len(vals) >= 3:
                cpb_stats[code] = (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)

        spend_mean = _stats.mean(all_spend)  if len(all_spend) >= 3 else 0.0
        spend_std  = _stats.stdev(all_spend) if len(all_spend) >= 3 else 0.0

        # Pre-compute cluster sizes from prescan cache NPPES data
        cluster_sizes = compute_address_clusters()
        auth_clusters = compute_auth_official_clusters()

        results = []
        for row in agg_rows:
            npi      = row["npi"]
            hcpcs    = hcpcs_by_npi.get(npi, [])
            timeline = timeline_by_npi.get(npi, [])

            s1 = billing_concentration(row, hcpcs)
            code = top_hcpcs_by_npi.get(npi, "")
            peer_mean, peer_std = peer_stats.get(code, (0.0, 0.0))
            s2 = revenue_per_bene_outlier(row, peer_mean, peer_std)
            cpb_mean, cpb_std = cpb_stats.get(code, (0.0, 0.0))
            s3 = claims_per_bene_anomaly(row, cpb_mean, cpb_std)
            s4 = billing_ramp_rate(timeline)
            s5 = bust_out_pattern(timeline)
            s6 = ghost_billing(row, timeline)
            s7 = total_spend_outlier(row, spend_mean, spend_std)
            s8 = billing_consistency(row, timeline)
            s9 = bene_concentration(row)
            s10 = upcoding_pattern(row, hcpcs)
            s11 = address_cluster_risk(row, cluster_sizes.get(npi, 0))
            s12 = oig_excluded(npi)
            s13 = specialty_mismatch(row, hcpcs)
            s14 = corporate_shell_risk(row, auth_clusters.get(npi, 0))
            s15 = dead_npi_billing(row)
            s16 = new_provider_explosion(row)
            s17 = geographic_impossibility(row)

            signals = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17]
            composite = sum(s["score"] * s["weight"] for s in signals)
            risk_score = round(min(composite, 100.0), 1)
            flags = [s for s in signals if s["flagged"]]

            results.append({
                **row,
                "risk_score": risk_score,
                "flags": flags,
                "signal_results": signals,
                "hcpcs": hcpcs_by_npi.get(npi, []),
                "timeline": timeline_by_npi.get(npi, []),
            })

        # ── Persist ────────────────────────────────────────────────────────────
        append_prescanned(results, save=False)
        record_batch_snapshots(results)
        new_offset = offset + len(agg_rows)
        set_scan_progress(new_offset, total, active_filter, batches + 1)  # saves to disk

        flagged_results = [r for r in results if r["risk_score"] > settings.RISK_THRESHOLD]
        flagged = len(flagged_results)
        if flagged_results:
            added = add_to_review_queue(flagged_results)
            log.info("Added %d new items to review queue", added)

        # Background: enrich ALL scanned providers with NPPES name/state/city
        from services.nppes_enricher import enrich_batch_with_nppes
        asyncio.create_task(enrich_batch_with_nppes([r["npi"] for r in results]))

        # Record data lineage for this scan batch
        _batch_claims = sum(r.get("total_claims") or 0 for r in results)
        _batch_duration = round(_time_mod.time() - _scan_start_time, 2)
        from services.data_discovery import _extract_date_from_url
        record_scan_run(
            dataset_url=get_parquet_path(),
            dataset_date=_extract_date_from_url(get_parquet_path()),
            provider_count=len(results),
            total_claims=int(_batch_claims),
            scan_type="batch",
            duration_sec=_batch_duration,
            state_filter=active_filter,
            details={"offset": new_offset, "total": total, "flagged": flagged},
        )

        log.info(
            "Batch done — %d providers scored (%d flagged), offset now %d/%d",
            len(results), flagged, new_offset, total,
        )

        remaining = total - new_offset
        set_prescan_status(
            0,
            f"Idle — {new_offset:,} of {total:,} providers scanned"
            + (f" · {remaining:,} remaining" if remaining > 0 else " · Complete"),
        )

        # Auto mode: schedule next batch if still running and more providers remain
        if _auto_mode and len(agg_rows) == batch_size:
            _hand_off = True  # tell finally not to release the lock
            await asyncio.sleep(0.5)
            asyncio.create_task(_run_scan_batch(batch_size, active_filter, force=force))
        else:
            _auto_mode = False

    except Exception as exc:
        log.error("Scan batch failed: %s", exc, exc_info=True)
        set_prescan_status(0, f"Error: {exc}")
        _auto_mode = False
    finally:
        if not _hand_off:
            _scan_running = False
            release_scan_lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    if load_prescanned_from_disk():
        prog = get_scan_progress()
        scanned = prog.get("offset", 0)
        total = prog.get("total_provider_count")
        msg = f"Loaded {len(get_prescanned())} providers from cache"
        if total:
            msg += f" · {scanned:,} of {total:,} scanned"
        set_prescan_status(0, msg)
        log.info(msg)

        # Backfill review queue from existing cache (catches providers scanned
        # before the review queue feature existed, and applies new threshold)
        flagged = [p for p in get_prescanned() if p.get("risk_score", 0) > settings.RISK_THRESHOLD]
        if flagged:
            added = add_to_review_queue(flagged)
            log.info("Backfilled review queue with %d providers from prescan cache", added)

        # Enrich any providers that are missing NPPES data (name/state/city)
        # Also re-enrich providers missing enumeration_date (added after initial enrichment)
        missing_nppes = [
            p["npi"] for p in get_prescanned()
            if not p.get("nppes") or not (p.get("nppes") or {}).get("enumeration_date")
        ]
        if missing_nppes:
            from services.nppes_enricher import enrich_batch_with_nppes
            from core.cache import invalidate_nppes_cache
            invalidate_nppes_cache()  # Clear stale NPPES cache so we get fresh data with enumeration_date
            asyncio.create_task(enrich_batch_with_nppes(missing_nppes))
            log.info("Queued NPPES enrichment for %d providers missing name/state/city or enumeration_date", len(missing_nppes))
    else:
        set_prescan_status(0, "Idle — use the Scan button to begin")
        log.info("No cache found — idle, waiting for manual scan trigger.")

    yield


app = FastAPI(
    title="Medicaid Fraud Detection API",
    description="Streams provider-level Medicaid claims from remote Parquet via DuckDB httpfs.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5200", "http://localhost:5173", "http://localhost:3000", "http://localhost:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware — must be added after CORS middleware
app.add_middleware(RateLimitMiddleware)

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
    global _scan_running
    if body is None:
        body = ScanBatchRequest()
    body.state_filter = _validate_state_filter(body.state_filter)
    if _scan_running or is_scan_running():
        raise HTTPException(409, "A scan is already in progress")
    if not acquire_scan_lock():
        raise HTTPException(409, "A scan is already in progress (another worker)")
    _scan_running = True
    task_id = enqueue_task("scan_batch", _run_scan_batch, body.batch_size, body.state_filter or None, body.force)
    return {"started": True, "batch_size": body.batch_size, "state_filter": body.state_filter, "force": body.force, "task_id": task_id}


@app.post("/api/prescan/auto-start", dependencies=[Depends(require_user)])
async def auto_start_scan(body: ScanBatchRequest = None):
    global _scan_running, _auto_mode
    if body is None:
        body = ScanBatchRequest()
    body.state_filter = _validate_state_filter(body.state_filter)
    _auto_mode = True
    if _scan_running or is_scan_running():
        return {"started": False, "auto_mode": True, "note": "Auto mode enabled — will continue after current batch"}
    if not acquire_scan_lock():
        return {"started": False, "auto_mode": True, "note": "Auto mode enabled — another worker is scanning"}
    _scan_running = True
    enqueue_task("auto_scan", _run_scan_batch, body.batch_size, body.state_filter or None, body.force)
    return {"started": True, "auto_mode": True, "batch_size": body.batch_size}


@app.post("/api/prescan/auto-stop", dependencies=[Depends(require_user)])
async def auto_stop_scan():
    global _auto_mode
    _auto_mode = False
    return {"auto_mode": False, "note": "Auto mode disabled — current batch will finish normally"}


@app.post("/api/prescan/rescore", dependencies=[Depends(require_user)])
async def rescore_cached_providers():
    """
    Re-run all fraud signals against every provider already in the prescan cache,
    using their stored hcpcs + timeline fields — no Parquet queries needed.
    Updates risk_score / flags / signal_results in-place and saves to disk.
    """
    from services.anomaly_detector import (
        billing_concentration,
        revenue_per_bene_outlier,
        claims_per_bene_anomaly,
        billing_ramp_rate,
        bust_out_pattern,
        ghost_billing,
        total_spend_outlier,
        billing_consistency,
        bene_concentration,
        upcoding_pattern,
        address_cluster_risk,
        oig_excluded,
        compute_address_clusters,
        specialty_mismatch,
        corporate_shell_risk,
        compute_auth_official_clusters,
        dead_npi_billing,
        new_provider_explosion,
        geographic_impossibility,
    )
    import statistics as _stats
    from collections import defaultdict as _dd

    providers = list(get_prescanned())
    if not providers:
        return {"rescored": 0, "message": "No cached providers to rescore"}

    # Build per-HCPCS-code peer pools (revenue, claims) and global spend pool
    peer_rpb: dict[str, list[float]] = _dd(list)
    peer_cpb: dict[str, list[float]] = _dd(list)
    all_spend: list[float] = []

    for p in providers:
        c_code = p.get("top_hcpcs") or ""
        if not c_code:
            hl = p.get("hcpcs") or []
            if hl: c_code = hl[0].get("hcpcs_code", "")
        rpb   = p.get("revenue_per_beneficiary") or 0.0
        cpb   = p.get("claims_per_beneficiary") or 0.0
        spend = p.get("total_paid") or 0.0
        if c_code and rpb  > 0: peer_rpb[c_code].append(float(rpb))
        if c_code and cpb  > 0: peer_cpb[c_code].append(float(cpb))
        if spend > 0: all_spend.append(float(spend))

    peer_stats: dict[str, tuple[float, float]] = {}
    for code, vals in peer_rpb.items():
        if len(vals) >= 3:
            peer_stats[code] = (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)

    cpb_stats: dict[str, tuple[float, float]] = {}
    for code, vals in peer_cpb.items():
        if len(vals) >= 3:
            cpb_stats[code] = (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)

    spend_mean = _stats.mean(all_spend)  if len(all_spend) >= 3 else 0.0
    spend_std  = _stats.stdev(all_spend) if len(all_spend) >= 3 else 0.0

    # Pre-compute cluster sizes from NPPES data
    cluster_sizes = compute_address_clusters()
    auth_clusters = compute_auth_official_clusters()

    rescored = []
    for p in providers:
        hcpcs    = p.get("hcpcs") or []
        timeline = p.get("timeline") or []
        npi      = p["npi"]

        s1 = billing_concentration(p, hcpcs)
        code = p.get("top_hcpcs") or (hcpcs[0].get("hcpcs_code", "") if hcpcs else "")
        pm, ps = peer_stats.get(code, (0.0, 0.0))
        s2 = revenue_per_bene_outlier(p, pm, ps)
        cpb_mean, cpb_std = cpb_stats.get(code, (0.0, 0.0))
        s3 = claims_per_bene_anomaly(p, cpb_mean, cpb_std)
        s4 = billing_ramp_rate(timeline)
        s5 = bust_out_pattern(timeline)
        s6 = ghost_billing(p, timeline)
        s7 = total_spend_outlier(p, spend_mean, spend_std)
        s8 = billing_consistency(p, timeline)
        s9 = bene_concentration(p)
        s10 = upcoding_pattern(p, hcpcs)
        s11 = address_cluster_risk(p, cluster_sizes.get(npi, 0))
        s12 = oig_excluded(npi)
        s13 = specialty_mismatch(p, hcpcs)
        s14 = corporate_shell_risk(p, auth_clusters.get(npi, 0))
        s15 = dead_npi_billing(p)
        s16 = new_provider_explosion(p)
        s17 = geographic_impossibility(p)

        signals = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17]
        risk_score = round(min(sum(s["score"] * s["weight"] for s in signals), 100.0), 1)
        flags = [s for s in signals if s["flagged"]]

        rescored.append({**p, "risk_score": risk_score, "flags": flags, "signal_results": signals})

    set_prescanned(rescored)

    # Rebuild review queue with updated scores
    from core.review_store import add_to_review_queue, get_review_queue, update_review_item
    flagged = [p for p in rescored if p["risk_score"] > settings.RISK_THRESHOLD]
    added = add_to_review_queue(flagged)

    log.info("Rescore complete: %d providers, %d flagged, %d new review items", len(rescored), len(flagged), added)
    return {
        "rescored": len(rescored),
        "flagged": len(flagged),
        "new_review_items": added,
        "peer_stats": {
            "cpb_mean":            round(cpb_mean, 2),
            "cpb_threshold_3sig":  round(cpb_mean + 3 * cpb_std, 2),
            "spend_mean":          round(spend_mean, 2),
            "spend_threshold_3sig": round(spend_mean + 3 * spend_std, 2),
        },
    }


async def _run_smart_scan(state_filter: Optional[str]):
    """
    Two-phase high-risk-first scan (requires local Parquet data).

    Phase 1 — Pull ALL provider aggregates in one DuckDB query, compute global
               peer stats, and pre-screen with z-score thresholds to identify
               candidates (any metric >= 2σ above mean, or total_paid >= $1M).

    Phase 2 — For each candidate batch, fetch HCPCS + timeline, then run all
               17 fraud signals for a full risk score.  Only candidates are stored
               in the prescan cache and review queue.
    """
    global _scan_running, _auto_mode, _smart_scan_mode

    from services.anomaly_detector import (
        billing_concentration,
        revenue_per_bene_outlier,
        claims_per_bene_anomaly,
        billing_ramp_rate,
        bust_out_pattern,
        ghost_billing,
        total_spend_outlier,
        billing_consistency,
        bene_concentration,
        upcoding_pattern,
        address_cluster_risk,
        oig_excluded,
        compute_address_clusters,
        specialty_mismatch,
        corporate_shell_risk,
        compute_auth_official_clusters,
        dead_npi_billing,
        new_provider_explosion,
        geographic_impossibility,
    )
    import statistics as _stats
    from collections import defaultdict as _dd

    BATCH = 500  # providers per Phase-2 batch

    try:
        _auto_mode = False  # smart scan is not auto-chainable
        _smart_scan_mode = True

        # Build state WHERE clause (parameterized)
        state_where = ""
        state_params: tuple = ()
        if state_filter:
            state_col = await asyncio.to_thread(detect_state_column)
            if state_col:
                state_where = f"{state_col} = ?"
                state_params = (state_filter,)
            else:
                log.warning("State column not found — state filter ignored")

        # ── Phase 1: all provider aggregates ─────────────────────────────────
        set_prescan_status(1, "Smart scan — loading all provider aggregates…")
        log.info("Smart scan Phase 1: querying all provider aggregates (state=%s)", state_filter)

        all_rows = await query_async(
            provider_aggregate_sql(where=state_where, limit=None, offset=0),
            state_params,
        )

        if not all_rows:
            set_prescan_status(0, "Smart scan: no providers found in dataset")
            return

        N = len(all_rows)
        log.info("Smart scan Phase 1: %d providers total", N)
        set_prescan_status(2, f"Smart scan — pre-screening {N:,} providers…")

        # Global peer stats for pre-screening (no HCPCS code grouping yet)
        all_rpb   = [float(r["revenue_per_beneficiary"] or 0) for r in all_rows if (r.get("revenue_per_beneficiary") or 0) > 0]
        all_cpb   = [float(r["claims_per_beneficiary"]  or 0) for r in all_rows if (r.get("claims_per_beneficiary")  or 0) > 0]
        all_spend = [float(r["total_paid"]              or 0) for r in all_rows if (r.get("total_paid")              or 0) > 0]

        rpb_mean   = _stats.mean(all_rpb)   if len(all_rpb)   >= 3 else 0.0
        rpb_std    = _stats.stdev(all_rpb)  if len(all_rpb)   >= 3 else 0.0
        cpb_mean   = _stats.mean(all_cpb)   if len(all_cpb)   >= 3 else 0.0
        cpb_std    = _stats.stdev(all_cpb)  if len(all_cpb)   >= 3 else 0.0
        spend_mean = _stats.mean(all_spend) if len(all_spend) >= 3 else 0.0
        spend_std  = _stats.stdev(all_spend)if len(all_spend) >= 3 else 0.0

        # Pre-screen: include providers 2σ+ above mean on any aggregate metric,
        # or with absolute spend >= $1M (always worth a full look)
        candidates = []
        for row in all_rows:
            rpb   = float(row.get("revenue_per_beneficiary") or 0)
            cpb   = float(row.get("claims_per_beneficiary")  or 0)
            spend = float(row.get("total_paid")              or 0)
            rpb_z   = (rpb   - rpb_mean)   / rpb_std   if rpb_std   > 0 else 0.0
            cpb_z   = (cpb   - cpb_mean)   / cpb_std   if cpb_std   > 0 else 0.0
            spend_z = (spend - spend_mean) / spend_std if spend_std > 0 else 0.0
            if max(rpb_z, cpb_z, spend_z) >= 2.0 or spend >= 1_000_000:
                candidates.append(row)

        n_candidates = len(candidates)
        log.info("Smart scan: %d/%d candidates (2σ+ or spend >= $1M)", n_candidates, N)
        set_prescan_status(2, f"Smart scan — {n_candidates:,} candidates identified out of {N:,} providers")
        set_scan_progress(0, n_candidates, state_filter, 0)

        if not candidates:
            set_prescan_status(0, f"Smart scan complete — no high-risk candidates found among {N:,} providers")
            set_scan_progress(N, N, state_filter, 0)
            return

        # ── Phase 2: full scoring for candidates ──────────────────────────────
        results: list[dict] = []

        for batch_i, i in enumerate(range(0, n_candidates, BATCH)):
            batch = candidates[i : i + BATCH]
            npi_list = [r["npi"] for r in batch]
            npi_in   = ", ".join(f"'{n}'" for n in npi_list)

            end = min(i + len(batch), n_candidates)
            set_prescan_status(3, f"Smart scan — scoring candidates {i+1:,}–{end:,} of {n_candidates:,}…")

            # HCPCS breakdown
            hcpcs_sql = f"""
            SELECT BILLING_PROVIDER_NPI_NUM AS npi, HCPCS_CODE AS hcpcs_code,
                   SUM(TOTAL_PAID) AS total_paid, SUM(TOTAL_CLAIMS) AS total_claims
            FROM read_parquet('{get_parquet_path()}')
            WHERE BILLING_PROVIDER_NPI_NUM IN ({npi_in})
            GROUP BY npi, hcpcs_code ORDER BY npi, total_paid DESC
            """
            hcpcs_rows = await query_async(hcpcs_sql)
            hcpcs_by_npi: dict[str, list[dict]] = {}
            for r in hcpcs_rows:
                hcpcs_by_npi.setdefault(r["npi"], []).append(r)

            # Monthly timeline
            timeline_sql = f"""
            SELECT BILLING_PROVIDER_NPI_NUM AS npi, CLAIM_FROM_MONTH AS month,
                   SUM(TOTAL_PAID) AS total_paid, SUM(TOTAL_CLAIMS) AS total_claims,
                   SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_unique_beneficiaries
            FROM read_parquet('{get_parquet_path()}')
            WHERE BILLING_PROVIDER_NPI_NUM IN ({npi_in})
            GROUP BY npi, month ORDER BY npi, month ASC
            """
            timeline_rows = await query_async(timeline_sql)
            timeline_by_npi: dict[str, list[dict]] = {}
            for r in timeline_rows:
                timeline_by_npi.setdefault(r["npi"], []).append(r)

            # Per-HCPCS-code peer pools for this batch
            peer_rpb: dict[str, list[float]] = _dd(list)
            peer_cpb: dict[str, list[float]] = _dd(list)

            top_hcpcs_by_npi: dict[str, str] = {
                npi: rows[0]["hcpcs_code"]
                for npi, rows in hcpcs_by_npi.items() if rows
            }
            # Seed from already-scored results
            for prev in results:
                c = prev.get("top_hcpcs") or ""
                if c and prev.get("revenue_per_beneficiary", 0) > 0:
                    peer_rpb[c].append(float(prev["revenue_per_beneficiary"]))
                if c and prev.get("claims_per_beneficiary", 0) > 0:
                    peer_cpb[c].append(float(prev["claims_per_beneficiary"]))
            # Add current batch
            for row in batch:
                code = top_hcpcs_by_npi.get(row["npi"])
                if code:
                    row["top_hcpcs"] = code
                    if row.get("revenue_per_beneficiary", 0) > 0:
                        peer_rpb[code].append(float(row["revenue_per_beneficiary"]))
                    if row.get("claims_per_beneficiary", 0) > 0:
                        peer_cpb[code].append(float(row["claims_per_beneficiary"]))

            peer_stats_map: dict[str, tuple[float, float]] = {
                code: (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)
                for code, vals in peer_rpb.items() if len(vals) >= 3
            }
            cpb_stats_map: dict[str, tuple[float, float]] = {
                code: (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)
                for code, vals in peer_cpb.items() if len(vals) >= 3
            }

            # Pre-compute cluster sizes from prescan cache NPPES data
            cluster_sizes = compute_address_clusters()
            auth_clusters = compute_auth_official_clusters()

            for row in batch:
                npi      = row["npi"]
                hcpcs    = hcpcs_by_npi.get(npi, [])
                timeline = timeline_by_npi.get(npi, [])
                code     = top_hcpcs_by_npi.get(npi, "")

                s1 = billing_concentration(row, hcpcs)
                pm, ps = peer_stats_map.get(code, (rpb_mean, rpb_std))
                s2 = revenue_per_bene_outlier(row, pm, ps)
                cpb_m, cpb_s = cpb_stats_map.get(code, (cpb_mean, cpb_std))
                s3 = claims_per_bene_anomaly(row, cpb_m, cpb_s)
                s4 = billing_ramp_rate(timeline)
                s5 = bust_out_pattern(timeline)
                s6 = ghost_billing(row, timeline)
                s7 = total_spend_outlier(row, spend_mean, spend_std)
                s8 = billing_consistency(row, timeline)
                s9 = bene_concentration(row)
                s10 = upcoding_pattern(row, hcpcs)
                s11 = address_cluster_risk(row, cluster_sizes.get(npi, 0))
                s12 = oig_excluded(npi)
                s13 = specialty_mismatch(row, hcpcs)
                s14 = corporate_shell_risk(row, auth_clusters.get(npi, 0))
                s15 = dead_npi_billing(row)
                s16 = new_provider_explosion(row)
                s17 = geographic_impossibility(row)

                signals    = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17]
                risk_score = round(min(sum(s["score"] * s["weight"] for s in signals), 100.0), 1)
                flags      = [s for s in signals if s["flagged"]]

                results.append({
                    **row,
                    "risk_score":    risk_score,
                    "flags":         flags,
                    "signal_results": signals,
                    "hcpcs":         hcpcs,
                    "timeline":      timeline,
                })

            # Merge in any NPPES data that enrichment tasks completed since last save,
            # so set_prescanned doesn't wipe name/state/city from earlier batches.
            current_by_npi = {p["npi"]: p for p in get_prescanned()}
            for r in results:
                if not r.get("nppes"):
                    cached = current_by_npi.get(r["npi"], {})
                    if cached.get("nppes"):
                        r["nppes"] = cached["nppes"]
                        r["state"] = cached.get("state", "")
                        r["city"] = cached.get("city", "")
                        r["provider_name"] = cached.get("provider_name", "")

            # Save results after every batch so progress survives interruptions
            set_prescanned(results)
            set_scan_progress(len(results), n_candidates, state_filter, batch_i + 1)

            # Update review queue incrementally too
            batch_flagged = [r for r in results[-len(batch):] if r["risk_score"] > settings.RISK_THRESHOLD]
            if batch_flagged:
                add_to_review_queue(batch_flagged)

            # Enrich this batch with NPPES in the background (name/state/city for providers list)
            from services.nppes_enricher import enrich_batch_with_nppes
            asyncio.create_task(enrich_batch_with_nppes([r["npi"] for r in batch]))

            high_risk_so_far = sum(1 for r in results if r["risk_score"] >= 50)
            set_prescan_status(
                3,
                f"Smart scan — scored {len(results):,} of {n_candidates:,} candidates"
                f" · {high_risk_so_far} high risk (≥50) found so far",
            )

        # ── Final persist (mark scan complete) ───────────────────────────────
        set_scan_progress(n_candidates, n_candidates, state_filter, (n_candidates - 1) // BATCH + 1)

        from services.nppes_enricher import enrich_batch_with_nppes
        asyncio.create_task(enrich_batch_with_nppes([r["npi"] for r in results]))

        high_risk_count = sum(1 for r in results if r["risk_score"] >= 50)
        msg = (
            f"Smart scan complete — {n_candidates:,} candidates scored "
            f"({high_risk_count} high risk ≥50) out of {N:,} total providers"
        )
        set_prescan_status(0, msg)
        log.info(msg)

    except Exception as exc:
        log.error("Smart scan failed: %s", exc, exc_info=True)
        set_prescan_status(0, f"Smart scan error: {exc}")
    finally:
        _scan_running = False
        release_scan_lock()
        _smart_scan_mode = False


class SmartScanRequest(BaseModel):
    state_filter: Optional[str] = None


@app.post("/api/prescan/smart-scan", dependencies=[Depends(require_user)])
async def smart_scan_endpoint(body: SmartScanRequest = None):
    """
    High-risk-first scan: loads ALL provider aggregates at once, pre-screens with
    z-score thresholds, then fully scores only the candidates.
    Requires local Parquet data (much faster than remote).
    """
    global _scan_running
    if not is_local():
        raise HTTPException(
            400,
            "Smart scan requires the local dataset — download it first via the Data Source card.",
        )
    if _scan_running or is_scan_running():
        raise HTTPException(409, "A scan is already in progress")
    if not acquire_scan_lock():
        raise HTTPException(409, "A scan is already in progress (another worker)")
    _scan_running = True
    state = _validate_state_filter(body.state_filter if body else None)
    task_id = enqueue_task("smart_scan", _run_smart_scan, state or None)
    return {"started": True, "mode": "smart", "task_id": task_id}


@app.post("/api/prescan/reset", dependencies=[Depends(require_admin)])
async def reset_scan_endpoint():
    global _scan_running, _auto_mode
    if _scan_running or is_scan_running():
        raise HTTPException(409, "Cannot reset while a scan is in progress")
    _auto_mode = False
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
    status["auto_mode"] = _auto_mode
    status["smart_scan_mode"] = _smart_scan_mode
    status["scan_locked"] = is_scan_running()
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
