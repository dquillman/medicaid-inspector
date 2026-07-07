"""
SAM.gov federal exclusion list check.
Uses the SAM.gov Entity/Exclusions API v4.

NOTE: SAM.gov requires a real API key — DEMO_KEY is not supported.
Register at https://sam.gov/profile/details to get a free Public API Key,
then set the SAM_API_KEY environment variable.
"""
import logging
import os
import httpx

log = logging.getLogger(__name__)

_SAM_API_BASE = "https://api.sam.gov/entity-information/v4/exclusions"
_SAM_API_KEY = os.environ.get("SAM_API_KEY", "")


async def check_sam_exclusion(npi: str = "", name: str = "") -> dict:
    """
    Check if a provider is on the SAM.gov federal exclusion list.

    Two sources, best-available:
      1. Live SAM.gov API (intraday-fresh) — when SAM_API_KEY is set.
      2. The KEYLESS public daily extract (core/sam_extract_store.py) — used
         when no key is configured, and as fallback if the API errors. The
         extract also enables NPI-first matching, which the API cannot do.
    Returns {"excluded": bool, "records": [...], ...}
    """
    if not _SAM_API_KEY:
        from core.sam_extract_store import check_extract
        return await check_extract(npi=npi, name=name)

    if not name:
        # API is name-indexed; without a name, the extract's NPI index is
        # strictly better than erroring out.
        from core.sam_extract_store import check_extract
        return await check_extract(npi=npi, name=name)

    try:
        params = {
            "api_key": _SAM_API_KEY,
            "exclusionName": name,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_SAM_API_BASE, params=params)
            if resp.status_code == 200:
                data = resp.json()
                # SAM v4 uses "excludedEntity" (not "results")
                records = data.get("excludedEntity", []) or []
                total = data.get("totalRecords", len(records))
                return {"excluded": total > 0, "records": records[:5]}
            else:
                log.warning("SAM.gov API returned %d - falling back to public extract",
                            resp.status_code)
                from core.sam_extract_store import check_extract
                return await check_extract(npi=npi, name=name)
    except Exception as e:
        log.warning("SAM.gov check failed (%s) - falling back to public extract", e)
        from core.sam_extract_store import check_extract
        return await check_extract(npi=npi, name=name)
