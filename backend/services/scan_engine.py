"""
Scan engine — extracted from main.py.

Manages the three scan modes (batch, auto/continuous, smart/high-risk-first)
and the rescore operation.  All scan state (running flag, auto mode, smart mode)
lives here so main.py only needs thin endpoint wrappers.
"""
import asyncio
import logging
import statistics as _stats
import time as _time_mod
from collections import defaultdict as _dd
from typing import Optional

from core.config import settings
from core.scan_lock import acquire_scan_lock, release_scan_lock, is_scan_running
from core.store import (
    get_prescanned, append_prescanned, set_prescanned,
    set_prescan_status, get_scan_progress, set_scan_progress,
)
from core.score_history import record_batch_snapshots
from core.lineage_store import record_scan_run
from data.duckdb_client import (
    query_async, provider_aggregate_sql, count_providers_sql,
    detect_state_column, get_parquet_path, is_local,
)

log = logging.getLogger(__name__)

# ── Scan state (per-process) ─────────────────────────────────────────────────
# TODO: These globals are per-process; broken under multi-worker deployments.
# Migrate to Redis or SQLite for horizontal scaling.

_scan_running = False
_auto_mode = False
_smart_scan_mode = False


def get_scan_state() -> dict:
    """Return current scan flags for status endpoints."""
    return {
        "auto_mode": _auto_mode,
        "smart_scan_mode": _smart_scan_mode,
        "scan_locked": is_scan_running(),
    }


def is_scan_active() -> bool:
    return _scan_running or is_scan_running()


def stop_auto_mode() -> None:
    global _auto_mode
    _auto_mode = False


# ── Shared signal scoring helper ─────────────────────────────────────────────

def _import_signals():
    """Lazy-import all 17 fraud signal detectors."""
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
    return {
        "billing_concentration": billing_concentration,
        "revenue_per_bene_outlier": revenue_per_bene_outlier,
        "claims_per_bene_anomaly": claims_per_bene_anomaly,
        "billing_ramp_rate": billing_ramp_rate,
        "bust_out_pattern": bust_out_pattern,
        "ghost_billing": ghost_billing,
        "total_spend_outlier": total_spend_outlier,
        "billing_consistency": billing_consistency,
        "bene_concentration": bene_concentration,
        "upcoding_pattern": upcoding_pattern,
        "address_cluster_risk": address_cluster_risk,
        "oig_excluded": oig_excluded,
        "compute_address_clusters": compute_address_clusters,
        "specialty_mismatch": specialty_mismatch,
        "corporate_shell_risk": corporate_shell_risk,
        "compute_auth_official_clusters": compute_auth_official_clusters,
        "dead_npi_billing": dead_npi_billing,
        "new_provider_explosion": new_provider_explosion,
        "geographic_impossibility": geographic_impossibility,
    }


def _score_provider(row: dict, hcpcs: list, timeline: list, npi: str,
                    top_code: str, peer_stats: dict, cpb_stats: dict,
                    spend_mean: float, spend_std: float,
                    cluster_sizes: dict, auth_clusters: dict,
                    sig) -> dict:
    """Run all 17 signals on a single provider and return enriched result."""
    s1 = sig["billing_concentration"](row, hcpcs)
    pm, ps = peer_stats.get(top_code, (0.0, 0.0))
    s2 = sig["revenue_per_bene_outlier"](row, pm, ps)
    cpb_m, cpb_s = cpb_stats.get(top_code, (0.0, 0.0))
    s3 = sig["claims_per_bene_anomaly"](row, cpb_m, cpb_s)
    s4 = sig["billing_ramp_rate"](timeline)
    s5 = sig["bust_out_pattern"](timeline)
    s6 = sig["ghost_billing"](row, timeline)
    s7 = sig["total_spend_outlier"](row, spend_mean, spend_std)
    s8 = sig["billing_consistency"](row, timeline)
    s9 = sig["bene_concentration"](row)
    s10 = sig["upcoding_pattern"](row, hcpcs)
    s11 = sig["address_cluster_risk"](row, cluster_sizes.get(npi, 0))
    s12 = sig["oig_excluded"](npi)
    s13 = sig["specialty_mismatch"](row, hcpcs)
    s14 = sig["corporate_shell_risk"](row, auth_clusters.get(npi, 0))
    s15 = sig["dead_npi_billing"](row)
    s16 = sig["new_provider_explosion"](row)
    s17 = sig["geographic_impossibility"](row)

    signals = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17]
    risk_score = round(min(sum(s["score"] * s["weight"] for s in signals), 100.0), 1)
    flags = [s for s in signals if s["flagged"]]

    return {
        **row,
        "risk_score": risk_score,
        "flags": flags,
        "signal_results": signals,
        "hcpcs": hcpcs,
        "timeline": timeline,
    }


def _build_peer_stats(providers: list, peer_rpb: dict, peer_cpb: dict, all_spend: list):
    """Compute per-HCPCS peer stats and global spend stats from accumulated data."""
    peer_stats = {}
    for code, vals in peer_rpb.items():
        if len(vals) >= 3:
            peer_stats[code] = (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)

    cpb_stats = {}
    for code, vals in peer_cpb.items():
        if len(vals) >= 3:
            cpb_stats[code] = (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)

    spend_mean = _stats.mean(all_spend) if len(all_spend) >= 3 else 0.0
    spend_std = _stats.stdev(all_spend) if len(all_spend) >= 3 else 0.0

    return peer_stats, cpb_stats, spend_mean, spend_std


# ── Batch scan ───────────────────────────────────────────────────────────────

async def run_scan_batch(batch_size: int, state_filter: Optional[str], force: bool = False):
    """
    Scans the next `batch_size` providers from the Parquet file.
    Appends results to the disk cache and updates scan progress.
    """
    global _scan_running, _auto_mode
    _hand_off = False

    sig = _import_signals()

    try:
        _scan_start_time = _time_mod.time()

        progress = get_scan_progress()
        if progress.get("offset", 0) == 0:
            try:
                from services.data_validator import run_validation
                set_prescan_status(1, "Running data quality validation…")
                await run_validation(sample_limit=2000)
                log.info("Pre-scan data validation complete")
            except Exception as val_err:
                log.warning("Data validation failed (non-fatal): %s", val_err)

        active_filter = state_filter or progress.get("state_filter")
        if state_filter and state_filter != progress.get("state_filter") and progress.get("offset", 0) > 0:
            log.info("State filter changed (%s → %s) — resetting offset", progress.get("state_filter"), state_filter)
            progress = {"offset": 0, "total_provider_count": None, "state_filter": state_filter, "batches_completed": 0, "last_batch_at": None}

        offset = progress.get("offset", 0)
        total = progress.get("total_provider_count")
        batches = progress.get("batches_completed", 0)

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

        # Build already_scanned + peer stats from cache
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

        # Incremental: skip already-scanned NPIs unless force=True
        if not force:
            new_rows = [r for r in agg_rows if r["npi"] not in already_scanned]
            if new_rows and len(new_rows) < len(agg_rows):
                skipped = len(agg_rows) - len(new_rows)
                log.info("Incremental: skipped %d already-scanned providers, %d new", skipped, len(new_rows))
            if not new_rows:
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
                    asyncio.create_task(run_scan_batch(batch_size, active_filter, force=False))
                    return
                return
            agg_rows = new_rows

        npi_list = [r["npi"] for r in agg_rows]
        npi_placeholders = ", ".join("?" for _ in npi_list)
        npi_params = tuple(npi_list)

        # Batch HCPCS
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

        # Batch timelines
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

        # Score providers
        set_prescan_status(3, f"Scoring {len(npi_list)} providers…")

        top_hcpcs_by_npi: dict[str, str] = {
            npi: rows[0]["hcpcs_code"]
            for npi, rows in hcpcs_by_npi.items() if rows
        }

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
            if code:
                row["top_hcpcs"] = code

        peer_stats, cpb_stats_map, spend_mean, spend_std = _build_peer_stats(
            agg_rows, peer_rpb, peer_cpb, all_spend
        )
        cluster_sizes = sig["compute_address_clusters"]()
        auth_clusters = sig["compute_auth_official_clusters"]()

        results = []
        for row in agg_rows:
            npi = row["npi"]
            results.append(_score_provider(
                row, hcpcs_by_npi.get(npi, []), timeline_by_npi.get(npi, []),
                npi, top_hcpcs_by_npi.get(npi, ""),
                peer_stats, cpb_stats_map, spend_mean, spend_std,
                cluster_sizes, auth_clusters, sig,
            ))

        # Persist
        append_prescanned(results, save=False)
        record_batch_snapshots(results)
        new_offset = offset + len(agg_rows)
        set_scan_progress(new_offset, total, active_filter, batches + 1)

        # Sync to GCS so data survives container restarts
        from core.gcs_sync import sync_after_scan
        asyncio.create_task(sync_after_scan())

        flagged_results = [r for r in results if r["risk_score"] > settings.RISK_THRESHOLD]
        flagged = len(flagged_results)

        from services.nppes_enricher import enrich_batch_with_nppes
        asyncio.create_task(enrich_batch_with_nppes([r["npi"] for r in results]))

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

        if _auto_mode and len(agg_rows) == batch_size:
            _hand_off = True
            await asyncio.sleep(0.5)
            asyncio.create_task(run_scan_batch(batch_size, active_filter, force=force))
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


# ── Rescore ──────────────────────────────────────────────────────────────────

async def rescore_cached_providers():
    """Re-run all fraud signals against every provider in the prescan cache."""
    sig = _import_signals()

    providers = list(get_prescanned())
    if not providers:
        return {"rescored": 0, "message": "No cached providers to rescore"}

    peer_rpb: dict[str, list[float]] = _dd(list)
    peer_cpb: dict[str, list[float]] = _dd(list)
    all_spend: list[float] = []

    for p in providers:
        c_code = p.get("top_hcpcs") or ""
        if not c_code:
            hl = p.get("hcpcs") or []
            if hl:
                c_code = hl[0].get("hcpcs_code", "")
        rpb = p.get("revenue_per_beneficiary") or 0.0
        cpb = p.get("claims_per_beneficiary") or 0.0
        spend = p.get("total_paid") or 0.0
        if c_code and rpb > 0:
            peer_rpb[c_code].append(float(rpb))
        if c_code and cpb > 0:
            peer_cpb[c_code].append(float(cpb))
        if spend > 0:
            all_spend.append(float(spend))

    peer_stats, cpb_stats_map, spend_mean, spend_std = _build_peer_stats(
        providers, peer_rpb, peer_cpb, all_spend
    )
    cluster_sizes = sig["compute_address_clusters"]()
    auth_clusters = sig["compute_auth_official_clusters"]()

    rescored = []
    for p in providers:
        hcpcs = p.get("hcpcs") or []
        timeline = p.get("timeline") or []
        npi = p["npi"]
        code = p.get("top_hcpcs") or (hcpcs[0].get("hcpcs_code", "") if hcpcs else "")

        rescored.append(_score_provider(
            p, hcpcs, timeline, npi, code,
            peer_stats, cpb_stats_map, spend_mean, spend_std,
            cluster_sizes, auth_clusters, sig,
        ))

    set_prescanned(rescored)

    # Sync to GCS
    from core.gcs_sync import sync_after_scan
    await sync_after_scan()

    flagged = [p for p in rescored if p["risk_score"] > settings.RISK_THRESHOLD]

    # Add flagged providers to review queue
    from core.review_store import add_to_review
    added = 0
    for p in flagged:
        if add_to_review(p):
            added += 1

    log.info("Rescore complete: %d providers, %d flagged", len(rescored), len(flagged))

    cpb_mean_val = _stats.mean([float(p.get("claims_per_beneficiary") or 0) for p in rescored if (p.get("claims_per_beneficiary") or 0) > 0]) if rescored else 0
    cpb_std_val = _stats.stdev([float(p.get("claims_per_beneficiary") or 0) for p in rescored if (p.get("claims_per_beneficiary") or 0) > 0]) if len(rescored) > 1 else 0

    return {
        "rescored": len(rescored),
        "flagged": len(flagged),
        "new_review_items": added,
        "peer_stats": {
            "cpb_mean": round(cpb_mean_val, 2),
            "cpb_threshold_3sig": round(cpb_mean_val + 3 * cpb_std_val, 2),
            "spend_mean": round(spend_mean, 2),
            "spend_threshold_3sig": round(spend_mean + 3 * spend_std, 2),
        },
    }


# ── Smart scan (high-risk-first) ─────────────────────────────────────────────

async def run_smart_scan(state_filter: Optional[str]):
    """Two-phase high-risk-first scan (requires local Parquet data)."""
    global _scan_running, _auto_mode, _smart_scan_mode

    sig = _import_signals()
    BATCH = 500

    try:
        _auto_mode = False
        _smart_scan_mode = True

        state_where = ""
        state_params: tuple = ()
        if state_filter:
            state_col = await asyncio.to_thread(detect_state_column)
            if state_col:
                state_where = f"{state_col} = ?"
                state_params = (state_filter,)
            else:
                log.warning("State column not found — state filter ignored")

        # Phase 1: all provider aggregates
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

        all_rpb = [float(r["revenue_per_beneficiary"] or 0) for r in all_rows if (r.get("revenue_per_beneficiary") or 0) > 0]
        all_cpb = [float(r["claims_per_beneficiary"] or 0) for r in all_rows if (r.get("claims_per_beneficiary") or 0) > 0]
        all_spend = [float(r["total_paid"] or 0) for r in all_rows if (r.get("total_paid") or 0) > 0]

        rpb_mean = _stats.mean(all_rpb) if len(all_rpb) >= 3 else 0.0
        rpb_std = _stats.stdev(all_rpb) if len(all_rpb) >= 3 else 0.0
        cpb_mean = _stats.mean(all_cpb) if len(all_cpb) >= 3 else 0.0
        cpb_std = _stats.stdev(all_cpb) if len(all_cpb) >= 3 else 0.0
        spend_mean = _stats.mean(all_spend) if len(all_spend) >= 3 else 0.0
        spend_std = _stats.stdev(all_spend) if len(all_spend) >= 3 else 0.0

        candidates = []
        for row in all_rows:
            rpb = float(row.get("revenue_per_beneficiary") or 0)
            cpb = float(row.get("claims_per_beneficiary") or 0)
            spend = float(row.get("total_paid") or 0)
            rpb_z = (rpb - rpb_mean) / rpb_std if rpb_std > 0 else 0.0
            cpb_z = (cpb - cpb_mean) / cpb_std if cpb_std > 0 else 0.0
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

        # Phase 2: full scoring for candidates
        results: list[dict] = []

        for batch_i, i in enumerate(range(0, n_candidates, BATCH)):
            batch = candidates[i: i + BATCH]
            npi_list = [r["npi"] for r in batch]
            npi_in = ", ".join(f"'{n}'" for n in npi_list)

            end = min(i + len(batch), n_candidates)
            set_prescan_status(3, f"Smart scan — scoring candidates {i+1:,}–{end:,} of {n_candidates:,}…")

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

            peer_rpb: dict[str, list[float]] = _dd(list)
            peer_cpb_map: dict[str, list[float]] = _dd(list)

            top_hcpcs_by_npi: dict[str, str] = {
                npi: rows[0]["hcpcs_code"]
                for npi, rows in hcpcs_by_npi.items() if rows
            }
            for prev in results:
                c = prev.get("top_hcpcs") or ""
                if c and prev.get("revenue_per_beneficiary", 0) > 0:
                    peer_rpb[c].append(float(prev["revenue_per_beneficiary"]))
                if c and prev.get("claims_per_beneficiary", 0) > 0:
                    peer_cpb_map[c].append(float(prev["claims_per_beneficiary"]))
            for row in batch:
                code = top_hcpcs_by_npi.get(row["npi"])
                if code:
                    row["top_hcpcs"] = code
                    if row.get("revenue_per_beneficiary", 0) > 0:
                        peer_rpb[code].append(float(row["revenue_per_beneficiary"]))
                    if row.get("claims_per_beneficiary", 0) > 0:
                        peer_cpb_map[code].append(float(row["claims_per_beneficiary"]))

            peer_stats_map: dict[str, tuple[float, float]] = {
                code: (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)
                for code, vals in peer_rpb.items() if len(vals) >= 3
            }
            cpb_stats_map: dict[str, tuple[float, float]] = {
                code: (_stats.mean(vals), _stats.stdev(vals) if len(vals) > 1 else 0.0)
                for code, vals in peer_cpb_map.items() if len(vals) >= 3
            }

            cluster_sizes = sig["compute_address_clusters"]()
            auth_clusters = sig["compute_auth_official_clusters"]()

            for row in batch:
                npi = row["npi"]
                code = top_hcpcs_by_npi.get(npi, "")
                pm, ps = peer_stats_map.get(code, (rpb_mean, rpb_std))
                cpb_m, cpb_s = cpb_stats_map.get(code, (cpb_mean, cpb_std))

                result = _score_provider(
                    row, hcpcs_by_npi.get(npi, []), timeline_by_npi.get(npi, []),
                    npi, code,
                    {code: (pm, ps)}, {code: (cpb_m, cpb_s)},
                    spend_mean, spend_std,
                    cluster_sizes, auth_clusters, sig,
                )
                results.append(result)

            current_by_npi = {p["npi"]: p for p in get_prescanned()}
            for r in results:
                if not r.get("nppes"):
                    cached = current_by_npi.get(r["npi"], {})
                    if cached.get("nppes"):
                        r["nppes"] = cached["nppes"]
                        r["state"] = cached.get("state", "")
                        r["city"] = cached.get("city", "")
                        r["provider_name"] = cached.get("provider_name", "")

            set_prescanned(results)
            set_scan_progress(len(results), n_candidates, state_filter, batch_i + 1)

            # Sync to GCS after each smart scan batch
            from core.gcs_sync import sync_after_scan
            asyncio.create_task(sync_after_scan())

            from services.nppes_enricher import enrich_batch_with_nppes
            asyncio.create_task(enrich_batch_with_nppes([r["npi"] for r in batch]))

            high_risk_so_far = sum(1 for r in results if r["risk_score"] >= 50)
            set_prescan_status(
                3,
                f"Smart scan — scored {len(results):,} of {n_candidates:,} candidates"
                f" · {high_risk_so_far} high risk (≥50) found so far",
            )

        # Final persist
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


# ── Public helpers for endpoints ─────────────────────────────────────────────

def start_batch_scan(batch_size: int, state_filter: Optional[str], force: bool = False) -> str:
    """Acquire lock, set running flag, enqueue batch scan. Returns task_id."""
    global _scan_running
    if not acquire_scan_lock():
        raise RuntimeError("A scan is already in progress (another worker)")
    _scan_running = True
    from core.task_queue import enqueue_task
    return enqueue_task("scan_batch", run_scan_batch, batch_size, state_filter, force)


def start_auto_scan(batch_size: int, state_filter: Optional[str], force: bool = False) -> str:
    """Enable auto mode and start scanning."""
    global _scan_running, _auto_mode
    _auto_mode = True
    if is_scan_active():
        return ""  # auto mode enabled, will chain after current batch
    if not acquire_scan_lock():
        return ""
    _scan_running = True
    from core.task_queue import enqueue_task
    return enqueue_task("auto_scan", run_scan_batch, batch_size, state_filter, force)


def start_smart_scan(state_filter: Optional[str]) -> str:
    """Start a smart scan. Returns task_id."""
    global _scan_running
    if not acquire_scan_lock():
        raise RuntimeError("A scan is already in progress (another worker)")
    _scan_running = True
    from core.task_queue import enqueue_task
    return enqueue_task("smart_scan", run_smart_scan, state_filter)
