from fastapi import APIRouter, Depends
from routes.auth import require_user, require_admin

router = APIRouter(prefix="/api/exclusions", tags=["exclusions"], dependencies=[Depends(require_user)])


@router.get("/data-sources")
async def exclusion_data_sources():
    """Freshness of every exclusion data source — so the UI/HAL can show WHEN
    each was last successfully updated, not just what it contains."""
    import os
    from core.oig_store import get_oig_stats
    from core.sam_extract_store import status as sam_status, ensure_loaded

    # touch the extract so its freshness reflects reality (cheap if already cached)
    try:
        await ensure_loaded()
    except Exception:
        pass

    oig = get_oig_stats()
    sam = sam_status()
    sam_mode = "live API + extract fallback" if os.environ.get("SAM_API_KEY") else "public extract (keyless)"
    return {
        "oig_leie": {
            "loaded": oig.get("loaded", False),
            "record_count": oig.get("record_count", 0),
            "source": "OIG LEIE (local monthly CSV)",
        },
        "sam": {**sam, "mode": sam_mode},
        "nppes": {
            "mode": "live registry lookup on demand (keyless)",
            "source": "CMS NPPES registry",
        },
    }


@router.post("/scan-all", dependencies=[Depends(require_admin)])
async def scan_all_exclusions():
    """
    Batch scan all providers in prescan cache against OIG LEIE
    and check NPI status from cached NPPES data.
    Admin-only — this is a heavy, long-running operation.
    """
    from core.exclusion_aggregator import run_batch_exclusion_scan
    return run_batch_exclusion_scan()


@router.get("/excluded")
async def excluded_providers():
    """All scanned providers that are on the OIG LEIE exclusion list.

    These are filtered out of the Providers list, Anomalies, Review Queue, and
    Fraud Brain — they're already barred from the program, so this page is
    their single home in the app.
    """
    import asyncio

    def _build() -> dict:
        from core.store import get_prescanned
        from core.oig_store import is_excluded
        rows = []
        total_paid = 0.0
        for p in get_prescanned():
            npi = p.get("npi", "")
            excluded, record = is_excluded(npi)
            if not excluded:
                continue
            paid = float(p.get("total_paid") or 0)
            total_paid += paid
            rows.append({
                "npi": npi,
                "provider_name": p.get("provider_name")
                                 or (p.get("nppes") or {}).get("name")
                                 or (record or {}).get("name", ""),
                "state": p.get("state")
                         or ((p.get("nppes") or {}).get("address") or {}).get("state", "")
                         or (record or {}).get("state", ""),
                "specialty": p.get("specialty") or (record or {}).get("specialty", ""),
                "total_paid": round(paid, 2),
                "risk_score": round(float(p.get("risk_score") or 0), 1),
                "flag_count": int(p.get("flag_count")
                                  or len([f for f in (p.get("flags") or []) if f.get("flagged")])),
                "excl_type": (record or {}).get("excl_type", ""),
                "excl_date": (record or {}).get("excl_date", ""),
            })
        rows.sort(key=lambda r: -r["total_paid"])
        return {
            "providers": rows,
            "total": len(rows),
            "total_paid": round(total_paid, 2),
        }

    return await asyncio.to_thread(_build)


@router.get("/summary")
async def exclusion_summary():
    """Return the latest batch exclusion scan results."""
    from core.exclusion_aggregator import get_batch_results
    results = get_batch_results()
    if results is None:
        return {
            "total_checked": 0,
            "oig_excluded_count": 0,
            "deactivated_count": 0,
            "new_npi_count": 0,
            "total_excluded": 0,
            "excluded_providers": [],
            "scanned_at": None,
            "never_scanned": True,
        }
    return results
