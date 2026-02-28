"""
CMS Open Payments data lookup.
Checks if a provider (by NPI) has received payments from pharmaceutical/device companies.
Uses the CMS Open Payments API (public, no key needed).
"""
import logging
import httpx

log = logging.getLogger(__name__)

_OP_API = "https://openpaymentsdata.cms.gov/api/1/datastore/query/58fbb622-68d9-43c1-8b84-7f625e6e7827/0"


async def get_open_payments(npi: str) -> dict:
    """
    Query CMS Open Payments for general payments to this provider.
    Returns summary of industry payments.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # The Open Payments API uses a datastore query format
            params = {
                "conditions[0][property]": "covered_recipient_npi",
                "conditions[0][value]": npi,
                "conditions[0][operator]": "=",
                "limit": 100,
                "offset": 0,
            }
            resp = await client.get(_OP_API, params=params)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                total_amount = sum(
                    float(r.get("total_amount_of_payment_usdollars", 0))
                    for r in results
                )
                companies: set[str] = set()
                for r in results:
                    company = r.get(
                        "applicable_manufacturer_or_applicable_gpo_making_payment_name", ""
                    )
                    if company:
                        companies.add(company)

                return {
                    "has_payments": len(results) > 0,
                    "payment_count": len(results),
                    "total_amount": round(total_amount, 2),
                    "unique_companies": sorted(companies)[:20],
                    "records": results[:10],  # first 10 for detail view
                }
            else:
                return {
                    "has_payments": False,
                    "payment_count": 0,
                    "total_amount": 0,
                    "error": f"API returned {resp.status_code}",
                }
    except Exception as e:
        log.warning("Open Payments lookup failed for %s: %s", npi, e)
        return {
            "has_payments": False,
            "payment_count": 0,
            "total_amount": 0,
            "error": str(e),
        }
