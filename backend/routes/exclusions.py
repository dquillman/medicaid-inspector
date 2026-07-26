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
    """Every provider barred from billing that billed anyway — across the FULL
    617k-NPI billing universe, not just the ~106k the prescan scores.

    This used to walk get_prescanned(), so it only ever saw providers above the
    $1M scan cutoff. That cutoff is right for the statistical signals and wrong
    here: 42 CFR 1001.1901 has no dollar threshold, and an excluded provider
    billing $200k is exactly as referable as one billing $2M. Measured
    2026-07-26, the old query missed 845 leads it could not see at all.

    Now served from the per-se sweep (scripts/build_perse_sweep.py), which also
    covers deactivated NPIs. Falls back to the old prescan walk if no sweep has
    been built yet, so the page is never empty on a fresh checkout.
    """
    import asyncio
    from core import perse_store

    def _from_sweep() -> dict | None:
        summary = perse_store.get_summary()
        if not summary.get("available"):
            return None
        rows = perse_store.list_leads(limit=100_000)["leads"]
        # Enrich with the scan cache where we have it — name/risk/flags only
        # exist for providers the prescan actually scored.
        from core.store import get_prescanned
        cached = {p.get("npi"): p for p in get_prescanned()}
        out = []
        for r in rows:
            p = cached.get(r["npi"]) or {}
            out.append({
                **r,
                "provider_name": r.get("provider_name")
                                 or p.get("provider_name")
                                 or (p.get("nppes") or {}).get("name", ""),
                "state": r.get("state")
                         or p.get("state")
                         or ((p.get("nppes") or {}).get("address") or {}).get("state", ""),
                "specialty": r.get("specialty") or p.get("specialty", ""),
                "risk_score": round(float(p.get("risk_score") or 0), 1),
                "flag_count": int(p.get("flag_count")
                                  or len([f for f in (p.get("flags") or []) if f.get("flagged")])),
                # Back-compat with the old response shape the page already reads.
                "excl_type": r.get("exclusion_type", ""),
                "excl_date": r.get("exclusion_date", ""),
            })
        return {
            "providers": out,
            "total": len(out),
            "total_paid": round(sum(r["total_paid"] for r in out), 2),
            "source": "perse_sweep",
            "generated_at": summary.get("generated_at"),
            "by_kind": summary.get("by_kind", {}),
            "kind_labels": perse_store.KIND_LABELS,
            "universe_note": (
                "Swept across every NPI that bills Medicaid, not only the "
                f"{summary.get('scanned_npis'):,} the risk model scores."
                if summary.get("scanned_npis") else None
            ),
        }

    def _from_prescan() -> dict:
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
                "kind": "active_exclusion",
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
                "in_scan_cache": True,
            })
        rows.sort(key=lambda r: -r["total_paid"])
        return {
            "providers": rows,
            "total": len(rows),
            "total_paid": round(total_paid, 2),
            "source": "prescan_only",
            "universe_note": (
                "No per-se sweep has been built, so this only covers providers the "
                "prescan scored. Run backend/scripts/build_perse_sweep.py to sweep "
                "the full billing universe."
            ),
        }

    def _build() -> dict:
        return _from_sweep() or _from_prescan()

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
