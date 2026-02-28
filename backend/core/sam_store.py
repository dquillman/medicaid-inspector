"""
SAM.gov federal exclusion list check.
Uses the SAM.gov Entity API (public, no key needed for basic queries).

NOTE: The SAM.gov API uses DEMO_KEY for limited testing (rate-limited).
For production use, register at https://sam.gov/content/entity-information
to obtain a personal API key and replace DEMO_KEY below.
"""
import logging
import httpx

log = logging.getLogger(__name__)

_SAM_API_BASE = "https://api.sam.gov/entity-information/v3/exclusions"


async def check_sam_exclusion(npi: str = "", name: str = "") -> dict:
    """
    Check if a provider is on the SAM.gov federal exclusion list.
    Can search by name since SAM doesn't always have NPI.
    Returns {"excluded": bool, "records": [...]}
    """
    try:
        params = {"api_key": "DEMO_KEY"}  # SAM.gov allows DEMO_KEY for limited queries
        if name:
            params["recipientName"] = name

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_SAM_API_BASE, params=params)
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("results", [])
                return {"excluded": len(records) > 0, "records": records[:5]}
            else:
                log.warning("SAM.gov API returned %d", resp.status_code)
                return {"excluded": False, "records": [], "error": f"API returned {resp.status_code}"}
    except Exception as e:
        log.warning("SAM.gov check failed: %s", e)
        return {"excluded": False, "records": [], "error": str(e)}
