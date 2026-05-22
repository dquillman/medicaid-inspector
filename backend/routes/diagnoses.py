"""
Diagnosis mix routes — wraps the CMS MUP-by-Provider dataset to surface
per-provider chronic-condition prevalence (the closest public proxy for
diagnoses-by-NPI; T-MSIS would require a CMS DUA).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from routes.auth import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["diagnoses"], dependencies=[Depends(require_user)])


@router.get("/{npi}/diagnoses")
async def provider_diagnoses(npi: str):
    """Per-provider diagnosis mix + diagnosis-procedure mismatch signal.

    - Returns 25 chronic-condition prevalence percentages from CMS MUP-by-Provider.
    - Computes the `diagnosis_procedure_mismatch` fraud signal by joining the
      provider's top HCPCS codes against Medicare chronic-condition prevalence.

    Returns has_data=False for providers not present in Medicare data
    (most Medicaid-only providers won't appear in MUP).
    """
    if not npi.isdigit() or len(npi) != 10:
        raise HTTPException(400, "NPI must be a 10-digit number")

    from services.mup_client import fetch_provider, summarize_provider
    from services.anomaly_detector import diagnosis_procedure_mismatch
    from services.risk_scorer import _hcpcs_sql
    from data.duckdb_client import query_async

    row = await fetch_provider(npi)
    if row is None:
        return {
            "npi": npi,
            "has_data": False,
            "message": "Provider not found in CMS MUP-by-Provider dataset. "
                       "This is normal for Medicaid-only providers — MUP only covers Medicare.",
        }

    # Pull Medicaid HCPCS rows to compute the mismatch signal
    hcpcs_sql, hcpcs_params = _hcpcs_sql(npi)
    try:
        hcpcs_rows = await query_async(hcpcs_sql, hcpcs_params)
    except Exception as e:
        logger.warning("HCPCS fetch failed for NPI=%s: %s", npi, e)
        hcpcs_rows = []

    mismatch = diagnosis_procedure_mismatch({"npi": npi}, hcpcs_rows, row)

    return {
        "npi": npi,
        "has_data": True,
        **summarize_provider(row),
        "mismatch_signal": mismatch,
    }
