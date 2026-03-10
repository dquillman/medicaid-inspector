from fastapi import APIRouter, Depends
from routes.auth import require_user

router = APIRouter(prefix="/api/exclusions", tags=["exclusions"], dependencies=[Depends(require_user)])


@router.post("/scan-all")
async def scan_all_exclusions():
    """
    Batch scan all providers in prescan cache against OIG LEIE
    and check NPI status from cached NPPES data.
    """
    from core.exclusion_aggregator import run_batch_exclusion_scan
    return run_batch_exclusion_scan()


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
