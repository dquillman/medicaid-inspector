"""
Async NPPES Provider Registry client.
Fetches provider identity data (name, address, taxonomy, entity type)
from the CMS NPI registry REST API.
"""
import httpx
from core.config import settings
from core.cache import cached_nppes


@cached_nppes
async def get_provider(npi: str) -> dict:
    """Fetch NPPES data for a single NPI. Returns normalized dict or {}."""
    url = f"{settings.NPPES_BASE_URL}?version=2.1&number={npi}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    if not results:
        return {}

    r = results[0]
    basic = r.get("basic", {})
    addresses = r.get("addresses", [])
    taxonomies = r.get("taxonomies", [])

    # Pick mailing address first, fall back to location
    address = next(
        (a for a in addresses if a.get("address_purpose") == "MAILING"),
        addresses[0] if addresses else {},
    )
    # Phone: prefer the PRACTICE LOCATION number, not the mailing one. State
    # intake forms ask for the provider's business phone, and the location line
    # is where the provider actually operates (for NPI 1235540212 the two
    # differ: location 704-290-4246 vs mailing 704-624-4620). We never parsed
    # telephone_number at all, so "provider phone" came back empty on every
    # referral and the answer sheet told Dave to leave a required NC field blank.
    location = next(
        (a for a in addresses if a.get("address_purpose") == "LOCATION"),
        address,
    )
    phone = (location.get("telephone_number") or address.get("telephone_number") or "").strip()
    fax = (location.get("fax_number") or address.get("fax_number") or "").strip()

    primary_taxonomy = next(
        (t for t in taxonomies if t.get("primary")), taxonomies[0] if taxonomies else {}
    )

    entity_type = r.get("enumeration_type", "")  # "NPI-1" individual, "NPI-2" org

    if entity_type == "NPI-2":
        name = basic.get("organization_name", "")
        full_name = name
    else:
        first = basic.get("first_name", "")
        last = basic.get("last_name", "")
        credential = basic.get("credential", "")
        full_name = f"{first} {last} {credential}".strip()

    return {
        "npi": npi,
        "entity_type": entity_type,
        "name": full_name,
        "status": basic.get("status", ""),
        # Business phone/fax — required by some state MFCU intakes (NC).
        "phone": phone,
        "fax": fax,
        "address": {
            "line1": address.get("address_1", ""),
            "line2": address.get("address_2", ""),
            "city": address.get("city", ""),
            "state": address.get("state", ""),
            "zip": address.get("postal_code", ""),
            "phone": phone,
        },
        "taxonomy": {
            "code": primary_taxonomy.get("code", ""),
            "description": primary_taxonomy.get("desc", ""),
            "license": primary_taxonomy.get("license", ""),
        },
        # All taxonomies, not just the primary. A second one is materially
        # relevant to a referral: 1235540212 reads as "Foster Care Agency" but
        # is ALSO a Psychiatric Residential Treatment Facility — the higher
        # reimbursement category, and the one consistent with its billing.
        "taxonomies": [
            {"code": t.get("code", ""), "description": t.get("desc", ""),
             "license": t.get("license", ""), "primary": bool(t.get("primary"))}
            for t in taxonomies
        ],
        "authorized_official": {
            "name": " ".join(filter(None, [
                basic.get("authorized_official_first_name", ""),
                basic.get("authorized_official_last_name", ""),
            ])),
            "title": basic.get("authorized_official_title_or_position", ""),
        } if entity_type == "NPI-2" else None,
        "last_updated": basic.get("last_updated", ""),
        "enumeration_date": basic.get("enumeration_date", ""),
        "deactivation_date": basic.get("deactivation_date", ""),
        "deactivation_reason_code": basic.get("deactivation_reason_code", ""),
    }


async def search_providers(name: str, limit: int = 20) -> list[dict]:
    """Search NPPES by provider name. Returns list of summary dicts."""
    # Use params= dict so httpx handles URL encoding — prevents header/query injection
    params = {"version": "2.1", "organization_name": name, "limit": str(limit)}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.NPPES_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    out = []
    for r in data.get("results", []):
        basic = r.get("basic", {})
        addresses = r.get("addresses", [])
        addr = addresses[0] if addresses else {}
        out.append({
            "npi": r.get("number", ""),
            "name": basic.get("organization_name")
                    or f"{basic.get('first_name','')} {basic.get('last_name','')}".strip(),
            "state": addr.get("state", ""),
            "city": addr.get("city", ""),
        })
    return out
