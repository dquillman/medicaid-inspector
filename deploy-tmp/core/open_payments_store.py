"""
CMS Open Payments data lookup.
Checks if a provider (by NPI) has received payments from pharmaceutical/device companies.

Uses the DKAN datastore query API on openpaymentsdata.cms.gov to fetch
General Payment records by covered_recipient_npi.
"""
import logging
from typing import List

import httpx

log = logging.getLogger(__name__)

# Dataset resource UUIDs for General Payment Data (one per program year).
# Add new years here as CMS publishes them.
_GENERAL_PAYMENT_DATASETS: List[str] = [
    "fb3a65aa-c901-4a38-a813-b04b00dfa2a9",   # 2023
]

_API_BASE = "https://openpaymentsdata.cms.gov/api/1/datastore/query"
_CMS_SEARCH = "https://openpaymentsdata.cms.gov/search"
_TIMEOUT = 20  # seconds


async def get_open_payments(npi: str) -> dict:
    """
    Query CMS Open Payments DKAN API for payments made to this NPI.
    Aggregates across all configured program-year datasets.
    """
    all_records: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for ds_id in _GENERAL_PAYMENT_DATASETS:
                url = f"{_API_BASE}/{ds_id}/0"
                params = {
                    "conditions[0][property]": "covered_recipient_npi",
                    "conditions[0][value]": npi,
                    "conditions[0][operator]": "=",
                    "limit": "100",
                    "format": "json",
                }
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results", [])
                        all_records.extend(results)
                    else:
                        log.warning("Open Payments API returned %d for dataset %s", resp.status_code, ds_id)
                except Exception as e:
                    log.warning("Open Payments query failed for dataset %s: %s", ds_id, e)
    except Exception as e:
        log.warning("Open Payments lookup failed: %s", e)
        return {
            "has_payments": False,
            "payment_count": 0,
            "total_amount": 0,
            "unique_companies": [],
            "records": [],
            "error": str(e),
        }

    if not all_records:
        return {
            "has_payments": False,
            "payment_count": 0,
            "total_amount": 0,
            "unique_companies": [],
            "records": [],
        }

    # Aggregate payment totals
    total_amount = 0.0
    companies: set[str] = set()
    for r in all_records:
        try:
            total_amount += float(r.get("total_amount_of_payment_usdollars", 0))
        except (ValueError, TypeError):
            pass
        company = r.get("submitting_applicable_manufacturer_or_applicable_gpo_name", "")
        if company:
            companies.add(company)

    return {
        "has_payments": True,
        "payment_count": len(all_records),
        "total_amount": round(total_amount, 2),
        "unique_companies": sorted(companies),
        "records": all_records[:20],  # Cap detail records
    }
