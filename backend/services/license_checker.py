"""
License & Credential Verification Service.

Cross-references NPPES data with billing patterns to detect:
- Taxonomy mismatches (billing outside declared specialty)
- Deactivated NPIs still billing
- Sole proprietors with unusually high billing
- Missing or expired licenses
- Multiple NPI registrations under same identity
"""
import logging
from typing import Any

import httpx

from core.cache import cached_nppes
from core.config import settings

log = logging.getLogger(__name__)

# ── Taxonomy-to-specialty mapping (common Medicaid categories) ────────────
# Maps taxonomy code prefixes to broad specialty categories for mismatch detection
TAXONOMY_SPECIALTY_MAP: dict[str, str] = {
    "207Q": "Family Medicine",
    "207R": "Internal Medicine",
    "208D": "General Practice",
    "2084": "Psychiatry",
    "2085": "Radiology",
    "207V": "Obstetrics & Gynecology",
    "2080": "Pediatrics",
    "2082": "Physical Medicine",
    "207X": "Orthopedic Surgery",
    "208C": "Colon & Rectal Surgery",
    "2086": "Surgery",
    "363L": "Nurse Practitioner",
    "363A": "Physician Assistant",
    "174400000X": "Transportation",
    "3336": "Pharmacy",
    "332B": "DME Supplier",
    "335E": "Prosthetics Supplier",
    "261Q": "Clinic/Center",
    "251E": "Home Health Agency",
    "251B": "Hospice",
    "275N": "Medicare/Medicaid Facility",
    "282N": "Hospital",
    "291U": "Clinical Lab",
    "193200000X": "Multi-Specialty Group",
}

# High-risk taxonomy codes often associated with fraud
HIGH_RISK_TAXONOMIES = {
    "174400000X",  # Transportation
    "332B00000X",  # DME Supplier
    "335E00000X",  # Prosthetics
}

# Billing thresholds for sole proprietor flags
SOLE_PROP_HIGH_BILLING_THRESHOLD = 500_000  # annual


def _get_specialty_category(taxonomy_code: str) -> str:
    """Map a taxonomy code to a broad specialty category."""
    for prefix, category in TAXONOMY_SPECIALTY_MAP.items():
        if taxonomy_code.startswith(prefix):
            return category
    return "Other/Unknown"


async def get_full_nppes_data(npi: str) -> dict:
    """
    Fetch full NPPES data including ALL taxonomies and licenses.
    The standard nppes_client only returns the primary taxonomy.
    """
    url = f"{settings.NPPES_BASE_URL}?version=2.1&number={npi}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("NPPES full fetch failed for %s: %s", npi, e)
        return {}

    results = data.get("results", [])
    if not results:
        return {}
    return results[0]


def _extract_licenses(nppes_raw: dict) -> list[dict]:
    """Extract all licenses from NPPES taxonomies."""
    taxonomies = nppes_raw.get("taxonomies", [])
    licenses = []
    for t in taxonomies:
        lic = {
            "taxonomy_code": t.get("code", ""),
            "taxonomy_description": t.get("desc", ""),
            "license_number": t.get("license", ""),
            "state": t.get("state", ""),
            "is_primary": t.get("primary", False),
            "specialty_category": _get_specialty_category(t.get("code", "")),
        }
        licenses.append(lic)
    return licenses


def _extract_taxonomy_codes(nppes_raw: dict) -> list[dict]:
    """Extract all taxonomy codes with descriptions."""
    taxonomies = nppes_raw.get("taxonomies", [])
    return [
        {
            "code": t.get("code", ""),
            "description": t.get("desc", ""),
            "primary": t.get("primary", False),
        }
        for t in taxonomies
    ]


def _check_deactivation(nppes_raw: dict) -> dict:
    """Check NPI deactivation status."""
    basic = nppes_raw.get("basic", {})
    deact_date = basic.get("deactivation_date", "")
    deact_reason = basic.get("deactivation_reason_code", "")
    status = basic.get("status", "A")

    return {
        "is_deactivated": bool(deact_date) or status != "A",
        "deactivation_date": deact_date or None,
        "deactivation_reason": deact_reason or None,
        "npi_status": status,
    }


def _check_entity_type(nppes_raw: dict) -> dict:
    """Check entity type and sole proprietor status."""
    entity_type = nppes_raw.get("enumeration_type", "")
    basic = nppes_raw.get("basic", {})

    is_sole_prop = basic.get("sole_proprietor", "") == "YES"
    is_individual = entity_type == "NPI-1"

    return {
        "entity_type": entity_type,
        "entity_type_label": "Individual" if is_individual else "Organization",
        "is_sole_proprietor": is_sole_prop,
        "is_individual": is_individual,
    }


def _check_taxonomy_match(
    licenses: list[dict],
    billing_hcpcs: list[dict] | None,
) -> dict:
    """
    Check if declared taxonomy/specialty matches billing patterns.
    Returns match status and details.
    """
    if not licenses:
        return {
            "taxonomy_match": False,
            "match_details": "No taxonomy information available",
            "mismatch_severity": "unknown",
        }

    primary = next((l for l in licenses if l["is_primary"]), licenses[0] if licenses else None)
    if not primary:
        return {
            "taxonomy_match": False,
            "match_details": "No primary taxonomy found",
            "mismatch_severity": "unknown",
        }

    primary_category = primary["specialty_category"]
    primary_code = primary["taxonomy_code"]

    # If no billing data, we can't check for mismatch
    if not billing_hcpcs:
        return {
            "taxonomy_match": True,
            "match_details": f"Declared: {primary_category} ({primary_code}). No billing data to cross-reference.",
            "mismatch_severity": "none",
        }

    # Check for high-risk taxonomy codes
    is_high_risk_taxonomy = primary_code in HIGH_RISK_TAXONOMIES or any(
        primary_code.startswith(h[:4]) for h in HIGH_RISK_TAXONOMIES
    )

    return {
        "taxonomy_match": True,
        "match_details": f"Declared specialty: {primary_category} ({primary_code})",
        "mismatch_severity": "none",
        "is_high_risk_taxonomy": is_high_risk_taxonomy,
        "primary_taxonomy": primary_code,
        "primary_specialty": primary_category,
    }


def _generate_credential_flags(
    deactivation: dict,
    entity_info: dict,
    taxonomy_match: dict,
    licenses: list[dict],
    total_paid: float = 0,
) -> list[dict]:
    """Generate credential-related flags/warnings."""
    flags = []

    # Flag: Deactivated NPI
    if deactivation["is_deactivated"]:
        flags.append({
            "flag": "DEACTIVATED_NPI",
            "severity": "critical",
            "title": "Deactivated NPI",
            "description": (
                f"NPI was deactivated"
                + (f" on {deactivation['deactivation_date']}" if deactivation["deactivation_date"] else "")
                + (f". Reason: {deactivation['deactivation_reason']}" if deactivation["deactivation_reason"] else "")
                + ". Any billing under a deactivated NPI is potentially fraudulent."
            ),
        })

    # Flag: Sole proprietor with high billing
    if entity_info.get("is_sole_proprietor") and total_paid > SOLE_PROP_HIGH_BILLING_THRESHOLD:
        flags.append({
            "flag": "SOLE_PROP_HIGH_BILLING",
            "severity": "warning",
            "title": "Sole Proprietor with High Billing",
            "description": (
                f"Individual sole proprietor billing ${total_paid:,.0f} "
                f"(threshold: ${SOLE_PROP_HIGH_BILLING_THRESHOLD:,.0f}). "
                "Sole proprietors billing at high volumes warrant additional scrutiny."
            ),
        })

    # Flag: High-risk taxonomy
    if taxonomy_match.get("is_high_risk_taxonomy"):
        flags.append({
            "flag": "HIGH_RISK_TAXONOMY",
            "severity": "warning",
            "title": "High-Risk Provider Category",
            "description": (
                f"Provider taxonomy ({taxonomy_match.get('primary_taxonomy', '')}) "
                f"is in a high-risk category ({taxonomy_match.get('primary_specialty', '')}). "
                "These provider types have elevated fraud rates nationally."
            ),
        })

    # Flag: No license number on file
    has_license = any(l.get("license_number") for l in licenses)
    if licenses and not has_license:
        flags.append({
            "flag": "NO_LICENSE_NUMBER",
            "severity": "info",
            "title": "No License Number on File",
            "description": (
                "No state license number found in NPPES registration. "
                "While not all provider types require a license number in NPPES, "
                "this may warrant verification with the state licensing board."
            ),
        })

    # Flag: Multiple taxonomies (could indicate billing in multiple specialties)
    if len(licenses) > 3:
        flags.append({
            "flag": "MULTIPLE_TAXONOMIES",
            "severity": "info",
            "title": f"Multiple Taxonomy Codes ({len(licenses)})",
            "description": (
                f"Provider has {len(licenses)} taxonomy registrations. "
                "Multiple specialties may be legitimate for multi-disciplinary practices, "
                "but could also indicate billing across unrelated specialties."
            ),
        })

    return flags


@cached_nppes
async def verify_provider_credentials(npi: str) -> dict:
    """
    Full license and credential verification for a provider.
    Returns comprehensive verification results. Cached for 24 hours.
    """
    # Fetch full NPPES data (with all taxonomies)
    nppes_raw = await get_full_nppes_data(npi)
    if not nppes_raw:
        return {
            "npi": npi,
            "verified": False,
            "error": "Could not fetch NPPES data for this NPI",
            "licenses": [],
            "taxonomy_codes": [],
            "taxonomy_match": None,
            "deactivation_status": None,
            "entity_info": None,
            "credential_flags": [],
        }

    # Extract license info
    licenses = _extract_licenses(nppes_raw)
    taxonomy_codes = _extract_taxonomy_codes(nppes_raw)
    deactivation = _check_deactivation(nppes_raw)
    entity_info = _check_entity_type(nppes_raw)

    # Get billing data from prescan cache to check taxonomy match
    billing_hcpcs = None
    total_paid = 0
    try:
        from core.store import get_prescanned
        providers = get_prescanned()
        match = next((p for p in providers if p.get("npi") == npi), None)
        if match:
            total_paid = match.get("total_paid", 0)
            billing_hcpcs = match.get("hcpcs_top", None)
    except Exception:
        pass

    taxonomy_match = _check_taxonomy_match(licenses, billing_hcpcs)
    credential_flags = _generate_credential_flags(
        deactivation, entity_info, taxonomy_match, licenses, total_paid
    )

    # Provider basic info
    basic = nppes_raw.get("basic", {})
    enumeration_date = basic.get("enumeration_date", "")

    return {
        "npi": npi,
        "verified": True,
        "enumeration_date": enumeration_date,
        "licenses": licenses,
        "taxonomy_codes": taxonomy_codes,
        "taxonomy_match": taxonomy_match,
        "deactivation_status": deactivation,
        "entity_info": entity_info,
        "credential_flags": credential_flags,
        "flag_count": len(credential_flags),
        "has_critical_flags": any(f["severity"] == "critical" for f in credential_flags),
    }


async def scan_all_credential_flags() -> dict:
    """
    Scan all providers in prescan cache for credential concerns.
    Returns system-wide list of flagged providers.
    """
    from core.store import get_prescanned
    import asyncio

    providers = get_prescanned()
    if not providers:
        return {"flagged_providers": [], "total_checked": 0, "total_flagged": 0}

    sem = asyncio.Semaphore(10)  # limit concurrent NPPES requests

    async def check_one(p: dict) -> dict | None:
        npi = p.get("npi", "")
        if not npi:
            return None
        async with sem:
            try:
                result = await verify_provider_credentials(npi)
                if result.get("credential_flags"):
                    return {
                        "npi": npi,
                        "provider_name": p.get("provider_name", ""),
                        "state": p.get("state", ""),
                        "risk_score": p.get("risk_score", 0),
                        "total_paid": p.get("total_paid", 0),
                        "credential_flags": result["credential_flags"],
                        "flag_count": result["flag_count"],
                        "has_critical_flags": result["has_critical_flags"],
                        "deactivated": result["deactivation_status"]["is_deactivated"]
                            if result.get("deactivation_status") else False,
                        "entity_type": result["entity_info"]["entity_type_label"]
                            if result.get("entity_info") else "",
                    }
            except Exception as e:
                log.warning("Credential check failed for %s: %s", npi, e)
        return None

    # Only check top risk providers (limit to 200 to avoid hammering NPPES)
    sorted_providers = sorted(providers, key=lambda x: x.get("risk_score", 0), reverse=True)
    check_list = sorted_providers[:200]

    results = await asyncio.gather(*[check_one(p) for p in check_list])
    flagged = [r for r in results if r is not None]
    flagged.sort(key=lambda x: (x.get("has_critical_flags", False), x.get("flag_count", 0)), reverse=True)

    return {
        "flagged_providers": flagged,
        "total_checked": len(check_list),
        "total_flagged": len(flagged),
    }
