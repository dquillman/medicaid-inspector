"""
CMS Open Payments data lookup.
Checks if a provider (by NPI) has received payments from pharmaceutical/device companies.

CMS retired their datastore query API in 2025.  The site now serves download-only
CSVs (multi-GB per year), so real-time per-NPI queries are no longer possible
without a local copy.

This module returns a helpful status with a direct link to the CMS search tool
where the user can look up the provider manually.
"""
import logging

log = logging.getLogger(__name__)

_CMS_SEARCH = "https://openpaymentsdata.cms.gov/search"


async def get_open_payments(npi: str) -> dict:
    """
    Return a status indicating CMS Open Payments must be checked manually.
    Includes a direct link to the CMS search tool.
    """
    return {
        "has_payments": False,
        "payment_count": 0,
        "total_amount": 0,
        "unavailable": True,
        "lookup_url": f"{_CMS_SEARCH}/{npi}",
        "message": (
            "CMS retired the Open Payments query API. "
            "Use the link below to search this provider on the CMS website."
        ),
    }
