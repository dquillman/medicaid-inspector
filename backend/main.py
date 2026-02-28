"""
Medicaid Fraud Detection Dashboard — FastAPI backend.
Run with: uvicorn main:app --reload --port 8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import settings
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
from routes import providers, anomalies, states, network, review
from core.review_store import load_review_from_disk, add_to_review_queue
from core.oig_store import load_oig_from_disk, download_oig_list

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Prevents two scan batches from running simultaneously
_scan_running = False
_auto_mode = False
_smart_scan_mode = False


async def _run_scan_batch(batch_size: int, state_filter: Optional[str]):
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
    )
    import statistics as _stats
    from collections import defaultdict as _dd

    try:
        progress = get_scan_progress()

        # If caller provides a different state filter, start offset over
        active_filter = state_filter or progress.get("state_filter")
        if state_filter and state_filter != progress.get("state_filter") and progress.get("offset", 0) > 0:
            log.info("State filter changed (%s → %s) — resetting offset", progress.get("state_filter"), state_filter)
            progress = {"offset": 0, "total_provider_count": None, "state_filter": state_filter, "batches_completed": 0, "last_batch_at": None}

        offset = progress.get("offset", 0)
        total = progress.get("total_provider_count")
        batches = progress.get("batches_completed", 0)

        # Build WHERE clause for state filter
        state_where = ""
        if active_filter:
            state_col = await asyncio.to_thread(detect_state_column)
            if state_col:
                state_where = f"{state_col} = '{active_filter}'"
            else:
                log.warning("State column not found in Parquet — state filter ignored")
                active_filter = None

        # ── Count total providers (first batch only) ──────────────────────────
        if total is None:
            label = f" in {active_filter}" if active_filter else ""
            set_prescan_status(1, f"Counting total providers{label}…")
            log.info("Counting distinct providers%s…", label)
            count_rows = await query_async(count_providers_sql(where=state_where))
            total = int(count_rows[0]["total"]) if count_rows else 0
            log.info("Total providers: %d", total)

        if total == 0:
            set_prescan_status(0, "No providers found")
            return

        # ── Step 1: provider aggregates ───────────────────────────────────────
        set_prescan_status(2, f"Fetching provider aggregates (offset {offset:,} of {total:,})…")
        log.info("Scan batch: offset=%d, batch_size=%d, state=%s", offset, batch_size, active_filter)
        agg_rows = await query_async(
            provider_aggregate_sql(where=state_where, limit=batch_size, offset=offset)
        )

        if not agg_rows:
            set_prescan_status(0, f"Scan complete — all {offset:,} providers checked")
            set_scan_progress(offset, total, active_filter, batches)
            log.info("Scan complete at offset %d", offset)
            return

        npi_list = [r["npi"] for r in agg_rows]
        npi_in = ", ".join(f"'{n}'" for n in npi_list)

        # ── Step 2: batch HCPCS ────────────────────────────────────────────────
        set_prescan_status(2, f"Fetching HCPCS breakdown for {len(npi_list)} providers…")
        hcpcs_sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM    AS npi,
            HCPCS_CODE                  AS hcpcs_code,
            SUM(TOTAL_PAID)             AS total_paid,
            SUM(TOTAL_CLAIMS)           AS total_claims
        FROM read_parquet('{get_parquet_path()}')
        WHERE BILLING_PROVIDER_NPI_NUM IN ({npi_in})
        GROUP BY npi, hcpcs_code
        ORDER BY npi, total_paid DESC
        """
        hcpcs_rows = await query_async(hcpcs_sql)
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
        WHERE BILLING_PROVIDER_NPI_NUM IN ({npi_in})
        GROUP BY npi, month
        ORDER BY npi, month ASC
        """
        timeline_rows = await query_async(timeline_sql)
        timeline_by_npi: dict[str, list[dict]] = {}
        for r in timeline_rows:
            timeline_by_npi.setdefault(r["npi"], []).append(r)

        # ── Step 4: score in Python ────────────────────────────────────────────
        set_prescan_status(3, f"Scoring {len(npi_list)} providers…")

        top_hcpcs_by_npi: dict[str, str] = {
            npi: rows[0]["hcpcs_code"]
            for npi, rows in hcpcs_by_npi.items() if rows
        }

        # Build peer stats from current batch PLUS all already-scanned providers
        # so z-scores are meaningful even on small batches
        peer_rpb: dict[str, list[float]] = _dd(list)
        # Seed with historical data from cache
        for cached in get_prescanned():
            c_code = cached.get("top_hcpcs") or ""
            if not c_code:
                # Derive top HCPCS from stored hcpcs list (present for recently scanned providers)
                hcpcs_list = cached.get("hcpcs") or []
                if hcpcs_list:
                    c_code = hcpcs_list[0].get("hcpcs_code", "")
            c_rpb = cached.get("revenue_per_beneficiary") or 0.0
            if c_code and c_rpb > 0:
                peer_rpb[c_code].append(float(c_rpb))
        # Add current batch
        for row in agg_rows:
            code = top_hcpcs_by_npi.get(row["npi"])
            rpb = row.get("revenue_per_beneficiary") or 0.0
            if code and rpb > 0:
                peer_rpb[code].append(float(rpb))
            # Store top_hcpcs in the result for future batches
            if code:
                row["top_hcpcs"] = code

        peer_stats: dict[str, tuple[float, float]] = {}
        for code, vals in peer_rpb.items():
            if len(vals) >= 3:
                m = _stats.mean(vals)
                s = _stats.stdev(vals) if len(vals) > 1 else 0.0
                peer_stats[code] = (m, s)

        # Per-HCPCS-code peer pools for claims_per_bene (same grouping as revenue outlier)
        # and global pool for total_spend_outlier
        peer_cpb:  dict[str, list[float]] = _dd(list)
        all_spend: list[float] = []
        for p in get_prescanned():
            c_code = p.get("top_hcpcs") or ""
            if not c_code:
                hl = p.get("hcpcs") or []
                if hl: c_code = hl[0].get("hcpcs_code", "")
            cpb   = p.get("claims_per_beneficiary") or 0
            spend = p.get("total_paid") or 0
            if c_code and cpb > 0: peer_cpb[c_code].append(float(cpb))
            if spend > 0: all_spend.append(float(spend))
        for row in agg_rows:
            code  = top_hcpcs_by_npi.get(row["npi"])
            cpb   = row.get("claims_per_beneficiary") or 0
            spend = row.get("total_paid") or 0
            if code and cpb > 0: peer_cpb[code].append(float(cpb))
            if spend > 0: all_spend.append(float(spend))

        cpb_stats: dict[str, tuple[float, float]] = {}
        for code, vals in peer_cpb.items():
            if len(vals) >= 3:
                cpb_stats[code] = (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)

        spend_mean = _stats.mean(all_spend)  if len(all_spend) >= 3 else 0.0
        spend_std  = _stats.stdev(all_spend) if len(all_spend) >= 3 else 0.0

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

            signals = [s1, s2, s3, s4, s5, s6, s7, s8]
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
        append_prescanned(results)
        new_offset = offset + len(agg_rows)
        set_scan_progress(new_offset, total, active_filter, batches + 1)

        flagged_results = [r for r in results if r["risk_score"] >= settings.RISK_THRESHOLD]
        flagged = len(flagged_results)
        if flagged_results:
            added = add_to_review_queue(flagged_results)
            log.info("Added %d new items to review queue", added)

        # Background: enrich ALL scanned providers with NPPES name/state/city
        from services.nppes_enricher import enrich_batch_with_nppes
        asyncio.create_task(enrich_batch_with_nppes([r["npi"] for r in results]))

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
            asyncio.create_task(_run_scan_batch(batch_size, active_filter))
        else:
            _auto_mode = False

    except Exception as exc:
        log.error("Scan batch failed: %s", exc, exc_info=True)
        set_prescan_status(0, f"Error: {exc}")
        _auto_mode = False
    finally:
        if not _hand_off:
            _scan_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initializing DuckDB with httpfs…")
    await asyncio.to_thread(get_connection)
    log.info("DuckDB ready.")

    load_review_from_disk()

    # Load OIG exclusion list — try cache first, download if missing
    if not load_oig_from_disk():
        asyncio.create_task(download_oig_list())

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
        flagged = [p for p in get_prescanned() if p.get("risk_score", 0) >= settings.RISK_THRESHOLD]
        if flagged:
            added = add_to_review_queue(flagged)
            log.info("Backfilled review queue with %d providers from prescan cache", added)

        # Enrich any providers that are missing NPPES data (name/state/city)
        missing_nppes = [p["npi"] for p in get_prescanned() if not p.get("nppes")]
        if missing_nppes:
            from services.nppes_enricher import enrich_batch_with_nppes
            asyncio.create_task(enrich_batch_with_nppes(missing_nppes))
            log.info("Queued NPPES enrichment for %d providers missing name/state/city", len(missing_nppes))
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

app.include_router(providers.router)
app.include_router(anomalies.router)
app.include_router(states.router)
app.include_router(network.router)
app.include_router(review.router)


# ── Scan control endpoints ────────────────────────────────────────────────────

class ScanBatchRequest(BaseModel):
    batch_size: int = settings.SCAN_BATCH_SIZE
    state_filter: Optional[str] = None


@app.post("/api/prescan/scan-batch")
async def trigger_scan_batch(body: ScanBatchRequest = None):
    global _scan_running
    if body is None:
        body = ScanBatchRequest()
    if _scan_running:
        raise HTTPException(409, "A scan is already in progress")
    _scan_running = True
    asyncio.create_task(_run_scan_batch(body.batch_size, body.state_filter or None))
    return {"started": True, "batch_size": body.batch_size, "state_filter": body.state_filter}


@app.post("/api/prescan/auto-start")
async def auto_start_scan(body: ScanBatchRequest = None):
    global _scan_running, _auto_mode
    if body is None:
        body = ScanBatchRequest()
    _auto_mode = True
    if _scan_running:
        # Auto mode will kick in once current batch finishes
        return {"started": False, "auto_mode": True, "note": "Auto mode enabled — will continue after current batch"}
    _scan_running = True
    asyncio.create_task(_run_scan_batch(body.batch_size, body.state_filter or None))
    return {"started": True, "auto_mode": True, "batch_size": body.batch_size}


@app.post("/api/prescan/auto-stop")
async def auto_stop_scan():
    global _auto_mode
    _auto_mode = False
    return {"auto_mode": False, "note": "Auto mode disabled — current batch will finish normally"}


@app.post("/api/prescan/rescore")
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

    rescored = []
    for p in providers:
        hcpcs    = p.get("hcpcs") or []
        timeline = p.get("timeline") or []

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

        signals = [s1, s2, s3, s4, s5, s6, s7, s8]
        risk_score = round(min(sum(s["score"] * s["weight"] for s in signals), 100.0), 1)
        flags = [s for s in signals if s["flagged"]]

        rescored.append({**p, "risk_score": risk_score, "flags": flags, "signal_results": signals})

    set_prescanned(rescored)

    # Rebuild review queue with updated scores
    from core.review_store import add_to_review_queue, get_review_queue, update_review_item
    flagged = [p for p in rescored if p["risk_score"] >= settings.RISK_THRESHOLD]
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
               8 fraud signals for a full risk score.  Only candidates are stored
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
    )
    import statistics as _stats
    from collections import defaultdict as _dd

    BATCH = 500  # providers per Phase-2 batch

    try:
        _auto_mode = False  # smart scan is not auto-chainable
        _smart_scan_mode = True

        # Build state WHERE clause
        state_where = ""
        if state_filter:
            state_col = await asyncio.to_thread(detect_state_column)
            if state_col:
                state_where = f"{state_col} = '{state_filter}'"
            else:
                log.warning("State column not found — state filter ignored")

        # ── Phase 1: all provider aggregates ─────────────────────────────────
        set_prescan_status(1, "Smart scan — loading all provider aggregates…")
        log.info("Smart scan Phase 1: querying all provider aggregates (state=%s)", state_filter)

        all_rows = await query_async(
            provider_aggregate_sql(where=state_where, limit=None, offset=0)
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

                signals    = [s1, s2, s3, s4, s5, s6, s7, s8]
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
            batch_flagged = [r for r in results[-len(batch):] if r["risk_score"] >= settings.RISK_THRESHOLD]
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
        _smart_scan_mode = False


class SmartScanRequest(BaseModel):
    state_filter: Optional[str] = None


@app.post("/api/prescan/smart-scan")
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
    if _scan_running:
        raise HTTPException(409, "A scan is already in progress")
    _scan_running = True
    state = body.state_filter if body else None
    asyncio.create_task(_run_smart_scan(state or None))
    return {"started": True, "mode": "smart"}


@app.post("/api/prescan/reset")
async def reset_scan_endpoint():
    global _scan_running, _auto_mode
    if _scan_running:
        raise HTTPException(409, "Cannot reset while a scan is in progress")
    _auto_mode = False
    reset_scan()
    set_prescan_status(0, "Idle — scan has been reset")
    return {"ok": True}


# ── Summary + status ──────────────────────────────────────────────────────────

@app.get("/api/summary")
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
    flagged    = sum(1 for p in prescanned if p.get("risk_score", 0) >= settings.RISK_THRESHOLD)
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


@app.get("/api/prescan/status")
async def prescan_status_endpoint():
    status = get_prescan_status()
    status["auto_mode"] = _auto_mode
    status["smart_scan_mode"] = _smart_scan_mode
    return status


@app.get("/health")
async def health():
    return {"status": "ok"}


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


@app.get("/api/data/status")
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


@app.post("/api/data/download")
async def start_download():
    """Start downloading the dataset to local disk (runs in background)."""
    if is_local():
        return {"ok": False, "message": "Dataset already downloaded locally"}
    if _download_state["active"]:
        return {"ok": False, "message": "Download already in progress"}
    asyncio.create_task(_do_download())
    return {"ok": True, "message": "Download started"}
