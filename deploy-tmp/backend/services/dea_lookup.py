"""
DEA (Drug Enforcement Administration) cross-reference lookup.
Checks DEA registration status for providers by NPI.

Uses NPPES data which may include practitioner identifiers,
and stubs an external DEA lookup for numbers not found locally.
"""
import logging
import random
from typing import Optional

log = logging.getLogger(__name__)

# Controlled substance schedules
SCHEDULES = ["II", "IIN", "III", "IIIN", "IV", "V"]


async def lookup_dea_by_npi(npi: str) -> dict:
    """
    Look up DEA registration status for a provider.

    Strategy:
    1. Check NPPES data for any linked identifiers
    2. If DEA number found, verify status (stubbed)
    3. Return structured DEA status
    """
    from data.nppes_client import get_provider

    nppes_data = {}
    try:
        nppes_data = await get_provider(npi)
    except Exception as e:
        log.warning("NPPES fetch failed for DEA lookup %s: %s", npi, e)

    # NPPES doesn't directly expose DEA numbers, but we can check
    # taxonomy to determine if the provider type typically needs DEA
    taxonomy = nppes_data.get("taxonomy", {}) if nppes_data else {}
    taxonomy_code = taxonomy.get("code", "")
    taxonomy_desc = taxonomy.get("description", "").lower()
    entity_type = nppes_data.get("entity_type", "")
    provider_name = nppes_data.get("name", "")

    # Determine if this provider type typically needs DEA
    prescriber_keywords = [
        "physician", "doctor", "nurse practitioner", "physician assistant",
        "dentist", "podiatrist", "optometrist", "psychiatr",
        "anesthesi", "surgery", "surgeon", "pain", "oncolog",
    ]
    likely_prescriber = any(kw in taxonomy_desc for kw in prescriber_keywords)
    is_individual = entity_type == "NPI-1"

    # Build a stubbed DEA record
    # In production, this would call the DEA ARCOS API or a verification service
    if likely_prescriber and is_individual:
        # Generate a plausible stub DEA status
        dea_status = _generate_stub_dea(npi, provider_name, taxonomy_desc)
    else:
        dea_status = {
            "dea_number": None,
            "active": None,
            "schedules": [],
            "expiration_date": None,
            "registration_type": None,
            "note": "Provider type does not typically require DEA registration",
        }

    return {
        "npi": npi,
        "provider_name": provider_name,
        "entity_type": entity_type,
        "taxonomy": taxonomy_desc,
        "likely_prescriber": likely_prescriber,
        "dea": dea_status,
        "flags": _check_dea_flags(dea_status, likely_prescriber),
        "source": "stub",
    }


def _generate_stub_dea(npi: str, name: str, specialty: str) -> dict:
    """Generate a plausible stub DEA record for testing purposes."""
    # Use NPI hash to produce consistent results for the same provider
    npi_hash = hash(npi) % 100

    if npi_hash < 85:
        # 85% have active DEA
        return {
            "dea_number": f"F{npi[:7]}",
            "active": True,
            "schedules": ["II", "IIN", "III", "IIIN", "IV", "V"],
            "expiration_date": "2027-06-30",
            "registration_type": "Practitioner",
            "state": None,
            "note": "Stubbed DEA record — verify with DEA ARCOS in production",
        }
    elif npi_hash < 95:
        # 10% have expired DEA
        return {
            "dea_number": f"F{npi[:7]}",
            "active": False,
            "schedules": ["II", "IIN", "III", "IIIN", "IV", "V"],
            "expiration_date": "2024-12-31",
            "registration_type": "Practitioner",
            "state": None,
            "note": "Stubbed DEA record — EXPIRED",
        }
    else:
        # 5% have no DEA on file
        return {
            "dea_number": None,
            "active": None,
            "schedules": [],
            "expiration_date": None,
            "registration_type": None,
            "note": "No DEA registration found (stubbed)",
        }


def _check_dea_flags(dea: dict, likely_prescriber: bool) -> list[dict]:
    """Generate flags based on DEA status."""
    flags = []

    if likely_prescriber and dea.get("dea_number") is None:
        flags.append({
            "flag": "no_dea_registration",
            "severity": "warning",
            "title": "No DEA Registration",
            "description": (
                "Provider type typically requires DEA registration for prescribing "
                "controlled substances, but no DEA number was found."
            ),
        })

    if dea.get("active") is False:
        flags.append({
            "flag": "dea_expired",
            "severity": "critical",
            "title": "DEA Registration Expired",
            "description": (
                f"DEA number {dea.get('dea_number')} expired on "
                f"{dea.get('expiration_date')}. Provider may be prescribing "
                "controlled substances without valid authorization."
            ),
        })

    if dea.get("active") is True and dea.get("schedules"):
        schedules = dea["schedules"]
        if "II" not in schedules and "IIN" not in schedules:
            flags.append({
                "flag": "limited_schedules",
                "severity": "info",
                "title": "Limited Schedule Authorization",
                "description": (
                    f"DEA registration does not include Schedule II. "
                    f"Authorized schedules: {', '.join(schedules)}"
                ),
            })

    return flags
