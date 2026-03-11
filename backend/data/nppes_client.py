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
        "address": {
            "line1": address.get("address_1", ""),
            "line2": address.get("address_2", ""),
            "city": address.get("city", ""),
            "state": address.get("state", ""),
            "zip": address.get("postal_code", ""),
        },
        "taxonomy": {
            "code": primary_taxonomy.get("code", ""),
            "description": primary_taxonomy.get("desc", ""),
            "license": primary_taxonomy.get("license", ""),
        },
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
    url = (
        f"{settings.NPPES_BASE_URL}?version=2.1"
        f"&organization_name={name}&limit={limit}"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
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
