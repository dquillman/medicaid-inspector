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
    Can search by name since SAM doesn't index by NPI.
    Returns {"excluded": bool, "records": [...]}
    """
    if not _SAM_API_KEY:
        return {
            "excluded": False,
            "records": [],
            "error": "No SAM_API_KEY configured. Get a free key at sam.gov/profile/details and set SAM_API_KEY env var.",
        }

    if not name:
        return {
            "excluded": False,
            "records": [],
            "error": "No provider name available for SAM.gov lookup (requires name, not NPI).",
        }

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
            elif resp.status_code == 403:
                return {
                    "excluded": False,
                    "records": [],
                    "error": "SAM.gov API key is invalid or rate-limited. Check your SAM_API_KEY.",
                }
            else:
                log.warning("SAM.gov API returned %d", resp.status_code)
                return {
                    "excluded": False,
                    "records": [],
                    "error": f"SAM.gov API returned {resp.status_code}",
                }
    except Exception as e:
        log.warning("SAM.gov check failed: %s", e)
        return {"excluded": False, "records": [], "error": str(e)}
