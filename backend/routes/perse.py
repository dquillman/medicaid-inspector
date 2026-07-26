"""
Per-se fraud sweep API — the leads that live BELOW the $1M scan cutoff.

The prescan ranks 106,660 providers; the billing universe is 617,503. That gap
is the right call for the statistical signals and the wrong one for the two
per-se checks, which need no peer statistics and carry no dollar threshold in
law. This router serves scripts/build_perse_sweep.py's output so those leads are
reachable, and every row links straight to the existing provider page — which
already renders a partial profile (NPPES identity + live exclusion checks) for
out-of-subset NPIs, and already carries the OIG/MFCU referral buttons.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from routes.auth import require_user
from core import perse_store

router = APIRouter(prefix="/api/perse", tags=["perse"], dependencies=[Depends(require_user)])


@router.get("/summary")
async def summary():
    """Counts + dollars per lead kind, and when the sweep was last built."""
    s = perse_store.get_summary()
    s["kind_labels"] = perse_store.KIND_LABELS
    if not s["available"]:
        s["note"] = (
            "No sweep has been built yet. Run backend/scripts/build_perse_sweep.py "
            "(it needs the OIG LEIE cache and npi_deactivations.json)."
        )
    return s


@router.get("")
async def list_leads(
    kind: str | None = Query(None, description="active_exclusion | deactivated_billing | deactivated_window | recovery_lead"),
    outside_scan_cache: bool | None = Query(
        None, description="true = only leads MFI's prescan cannot see at all"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    if kind and kind not in perse_store.KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(perse_store.KINDS)}")
    result = perse_store.list_leads(
        kind=kind, outside_scan_cache=outside_scan_cache, limit=limit, offset=offset)
    result["kind_labels"] = perse_store.KIND_LABELS
    return result


@router.get("/{npi}")
async def lead_for_npi(npi: str):
    """Per-se status for one NPI — powers a badge on the provider page."""
    if not npi.isdigit() or len(npi) != 10:
        raise HTTPException(400, "NPI must be a 10-digit number")
    lead = perse_store.get_lead(npi)
    if lead is None:
        return {"npi": npi, "has_lead": False}
    return {"npi": npi, "has_lead": True, "lead": lead,
            "label": perse_store.KIND_LABELS.get(lead.get("kind"), lead.get("kind"))}
