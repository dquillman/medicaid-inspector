"""
Data pipeline admin routes — dataset discovery, validation, lineage tracking.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, HttpUrl
from routes.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["data-pipeline"], dependencies=[Depends(require_admin)])


# ── Dataset Info & Refresh (#8) ──────────────────────────────────────────────

@router.get("/dataset-info")
async def dataset_info():
    """Current dataset URL, date, row count, and freshness info."""
    from services.data_discovery import get_dataset_info, count_dataset_rows

    info = get_dataset_info()
    # Lazy-count rows if not yet known
    if info.get("row_count") is None:
        info["row_count"] = await count_dataset_rows()
    return info


@router.get("/data-freshness")
async def data_freshness():
    """Age of each refreshable artifact — powers the Scan & Data freshness strip.
    Returns raw timestamps; the frontend computes ages + cadence colors."""
    import time as _t
    import pathlib as _pl
    now = _t.time()

    info = {}
    try:
        from services.data_discovery import get_dataset_info
        info = get_dataset_info() or {}
    except Exception:
        pass

    pq = _pl.Path(__file__).parent.parent / "data" / "medicaid-provider-spending.parquet"
    ds_mtime = pq.stat().st_mtime if pq.exists() else None

    # On Cloud Run the local parquet mtime resets every cold start, so the true
    # "when did we last refresh the core data" signal is the GCS object's upload
    # time. Prefer it when reachable (best-effort; falls back to local mtime).
    gcs_updated = None
    try:
        from core.gcs_sync import _get_bucket, _PARQUET_BLOB
        bucket = _get_bucket()
        if bucket:
            blob = bucket.blob(_PARQUET_BLOB)
            if blob.exists():
                blob.reload()
                if blob.updated:
                    gcs_updated = blob.updated.timestamp()
    except Exception:
        pass

    deact = 0
    try:
        from core.deactivation_store import count as _dc
        deact = _dc()
    except Exception:
        pass

    oig_count = 0
    try:
        from core.oig_store import get_oig_stats
        oig_count = int((get_oig_stats() or {}).get("record_count") or 0)
    except Exception:
        pass

    last_scan = None
    try:
        from core.lineage_store import get_lineage
        last_scan = (get_lineage(1, 1) or {}).get("summary", {}).get("latest_scan")
    except Exception:
        pass

    generated_at = None
    try:
        from services.precomputed_store import get_generated_at
        generated_at = get_generated_at()
    except Exception:
        pass

    return {
        "now": now,
        "core_dataset": {
            "detected_date": info.get("detected_date"),
            "is_local": bool(info.get("is_local")),
            "mtime": ds_mtime,
            "gcs_updated": gcs_updated,
        },
        "derived_generated_at": generated_at,   # ISO str: precompute/NPPES/deactivation refresh
        "deactivation_count": deact,
        "oig_record_count": oig_count,
        "last_scan_at": last_scan,
    }


@router.post("/dataset-refresh")
async def dataset_refresh():
    """Check CMS/HHS for a newer dataset and optionally switch to it."""
    from services.data_discovery import check_for_updates
    return await check_for_updates()


class DatasetSwitchBody(BaseModel):
    url: HttpUrl  # Pydantic validates that this is a well-formed http/https URL


@router.post("/dataset-switch")
async def dataset_switch(body: DatasetSwitchBody):
    """
    Switch to a specific dataset URL.
    Body: { "url": "https://..." }
    Invalidates caches so the next scan uses the new data.
    """
    from services.data_discovery import switch_dataset
    from core.cache import invalidate_query_cache

    url_str = str(body.url)
    # Restrict to http/https to block file://, ftp://, internal SSRF attempts
    if not url_str.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must use http or https scheme")

    result = switch_dataset(url_str)
    invalidate_query_cache()
    return result


# ── Data Validation (#9) ─────────────────────────────────────────────────────

@router.get("/data-quality")
async def data_quality():
    """Return the latest data validation summary."""
    from services.data_validator import get_validation_result
    return get_validation_result()


@router.post("/data-quality/run")
async def run_data_quality(sample_limit: int = Query(5000, ge=100, le=50000)):
    """Run data validation on the active dataset (sampled)."""
    from services.data_validator import run_validation
    return await run_validation(sample_limit=sample_limit)


# ── MUP-by-Provider local cache (#18 — diagnosis signal) ────────────────────

@router.get("/mup-status")
async def mup_status():
    """Status of the local MUP-by-Provider parquet cache."""
    from services import mup_cache
    info = mup_cache.status()
    if info["is_local"] and info["row_count"] is None:
        info["row_count"] = mup_cache.row_count()
    return info


@router.post("/mup-refresh")
async def mup_refresh():
    """Download CMS MUP-by-Provider CSV → parquet (background task).

    Powers the diagnosis_procedure_mismatch signal during batch scans.
    Re-running this fetches the latest annual MUP release.
    """
    import asyncio
    from services import mup_cache

    if mup_cache._download_state["active"]:
        return {"ok": False, "message": "MUP download already in progress"}
    asyncio.create_task(mup_cache.download_and_convert())
    return {"ok": True, "message": "MUP download started"}


# ── Data Lineage (#11) ───────────────────────────────────────────────────────

@router.get("/lineage")
async def lineage(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Scan history with dataset versions — shows what data was scanned and when."""
    from core.lineage_store import get_lineage
    return get_lineage(page=page, limit=limit)
