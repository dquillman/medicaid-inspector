"""
Medicare Fee-for-Service Provider Utilization lookup via CMS Socrata API.
Fetches Medicare utilization data for a given NPI from the CMS
Provider Utilization & Payment Data (Medicare Physician & Other
Practitioners by Provider).

Uses the same caching pattern as NPPES client.
"""
import logging
import httpx
from core.cache import cached_nppes  # reuse 24-hour TTL cache

log = logging.getLogger(__name__)

# CMS Medicare Physician & Other Practitioners — by Provider
# Dataset identifier: fs4p-t5eq (2022 data, latest public)
_MEDICARE_UTIL_URL = (
    "https://data.cms.gov/resource/fs4p-t5eq.json"
)


@cached_nppes
async def get_medicare_utilization(npi: str) -> dict:
    """
    Fetch Medicare utilization data for a single NPI.
    Returns normalized summary dict or empty dict if no data.
    """
    params = {
        "rndrng_npi": npi,
        "$limit": 500,  # all HCPCS rows for this provider
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_MEDICARE_UTIL_URL, params=params)
            resp.raise_for_status()
            rows = resp.json()
    except httpx.HTTPStatusError as e:
        log.warning("Medicare API HTTP error for NPI %s: %s", npi, e)
        return {"error": f"CMS API returned {e.response.status_code}"}
    except Exception as e:
        log.warning("Medicare API error for NPI %s: %s", npi, e)
        return {"error": str(e)}

    if not rows:
        return {
            "has_data": False,
            "npi": npi,
            "medicare_total_submitted": 0,
            "medicare_total_paid": 0,
            "medicare_beneficiaries": 0,
            "medicare_total_services": 0,
            "medicare_avg_per_bene": 0,
            "top_hcpcs": [],
            "provider_type": None,
        }

    total_submitted = 0.0
    total_paid = 0.0
    total_beneficiaries = 0
    total_services = 0
    provider_type = None
    hcpcs_map: dict[str, dict] = {}

    for row in rows:
        submitted = float(row.get("avg_sbmtd_chrg", 0)) * int(row.get("tot_srvcs", 0))
        paid = float(row.get("avg_mdcr_pymt_amt", 0)) * int(row.get("tot_srvcs", 0))
        services = int(row.get("tot_srvcs", 0))
        benes = int(row.get("tot_benes", 0))

        total_submitted += submitted
        total_paid += paid
        total_services += services
        # beneficiaries is per-HCPCS, so we track max unique across rows
        # (can't simply sum because same beneficiary may appear in multiple HCPCS)
        total_beneficiaries = max(total_beneficiaries, benes)

        if not provider_type:
            provider_type = row.get("rndrng_prvdr_type", None)

        code = row.get("hcpcs_cd", "")
        if code:
            if code not in hcpcs_map:
                hcpcs_map[code] = {
                    "hcpcs_code": code,
                    "description": row.get("hcpcs_desc", ""),
                    "total_paid": 0.0,
                    "total_services": 0,
                    "total_beneficiaries": 0,
                }
            hcpcs_map[code]["total_paid"] += paid
            hcpcs_map[code]["total_services"] += services
            hcpcs_map[code]["total_beneficiaries"] = max(
                hcpcs_map[code]["total_beneficiaries"], benes
            )

    # Sort HCPCS by total paid descending, return top 10
    top_hcpcs = sorted(hcpcs_map.values(), key=lambda x: x["total_paid"], reverse=True)[:10]

    # Sum total unique beneficiaries from the provider-level bene count
    # Use the tot_benes from the first row as an approximation of unique benes
    # (CMS provides tot_benes at HCPCS level, not truly additive)
    unique_benes = max(int(row.get("tot_benes", 0)) for row in rows) if rows else 0

    avg_per_bene = total_paid / unique_benes if unique_benes > 0 else 0

    return {
        "has_data": True,
        "npi": npi,
        "medicare_total_submitted": round(total_submitted, 2),
        "medicare_total_paid": round(total_paid, 2),
        "medicare_beneficiaries": unique_benes,
        "medicare_total_services": total_services,
        "medicare_avg_per_bene": round(avg_per_bene, 2),
        "top_hcpcs": top_hcpcs,
        "provider_type": provider_type,
        "hcpcs_count": len(hcpcs_map),
    }
