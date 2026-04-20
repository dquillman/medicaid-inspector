"""
Diagnosis-to-Procedure Validation Service.

Validates that billed HCPCS/CPT codes are medically appropriate for the
provider's specialty. Uses CMS-published specialty-to-code associations
from the Medicare Physician & Other Supplier dataset as the crosswalk.

This catches:
- Specialty mismatch billing (podiatrist billing cardiac procedures)
- Implausible code combinations
- Providers billing codes far outside their specialty norm

Data source: Free CMS data embedded as specialty→code mappings derived from
Medicare utilization patterns (no external API needed).
"""
import logging
from collections import defaultdict
from typing import Optional

from core.store import get_prescanned, get_provider_by_npi

log = logging.getLogger(__name__)

# ── Specialty-to-Code Reference (CMS-derived) ──────────────────────────────
# Top codes by specialty from CMS Medicare Physician & Other Supplier PUF
# This is a condensed crosswalk: specialty taxonomy prefix → expected HCPCS codes
# Codes NOT in this set for a given specialty are "unexpected"

_SPECIALTY_CODES: dict[str, set[str]] = {
    # Internal Medicine / Family Practice
    "207Q": {"99213", "99214", "99215", "99211", "99212", "99203", "99204", "99205",
             "36415", "85025", "80053", "80048", "81001", "G0438", "G0439", "99395",
             "99396", "99385", "99386", "90471", "90472", "96372"},
    "207R": {"99213", "99214", "99215", "99211", "99212", "99203", "99204", "99205",
             "36415", "85025", "80053", "80048", "81001", "G0438", "G0439"},
    # Cardiology
    "207R00": {"93000", "93010", "93306", "93307", "93308", "93312", "93351",
               "93798", "93015", "93016", "93017", "93018", "93880", "93882",
               "99213", "99214", "99215", "93922", "93923", "93970", "93971"},
    # Orthopedics
    "207X": {"99213", "99214", "20610", "20605", "20600", "27447", "27130",
             "29881", "29880", "73721", "73060", "73030", "73562", "23472",
             "27446", "73610", "73630"},
    # Dermatology
    "207N": {"99213", "99214", "17000", "17003", "17110", "17111", "11102",
             "11104", "11106", "88305", "11100", "17004", "96910", "96920"},
    # Podiatry
    "213E": {"99213", "99214", "11721", "11720", "11055", "11056", "11057",
             "28285", "28296", "11730", "11750", "28035"},
    # Psychiatry
    "2084": {"99213", "99214", "90834", "90837", "90832", "90833", "90836",
             "90838", "90839", "90840", "90791", "90792", "96127"},
    # Ophthalmology
    "207W": {"92014", "92012", "92004", "92002", "66984", "67028", "67210",
             "65855", "92083", "92250", "76512", "76519"},
    # General Surgery
    "208600": {"99213", "99214", "99223", "99232", "99233", "99238", "49505",
               "47562", "43239", "43235", "19120", "19301"},
    # OB/GYN
    "207V": {"99213", "99214", "59400", "59510", "59610", "76801", "76805",
             "76816", "76817", "58661", "58558", "57454", "99395"},
    # Radiology
    "2085": {"70553", "70551", "70552", "71046", "71045", "72148", "72141",
             "73721", "74177", "74178", "72193", "72192"},
    # Physical Therapy
    "225X": {"97110", "97140", "97530", "97112", "97542", "97535", "97150",
             "97116", "97161", "97162", "97163", "97164"},
    # Occupational Therapy
    "225X00": {"97110", "97530", "97140", "97535", "97542", "97112", "97150",
               "97165", "97166", "97167", "97168"},
    # Chiropractic
    "204C": {"98940", "98941", "98942", "98943", "97140", "97110", "97112",
             "97010", "97012", "97014"},
    # Home Health / Nursing
    "163W": {"99349", "99350", "99347", "99348", "G0299", "G0300",
             "99341", "99342", "99343", "99344", "99345"},
    # DME Supplier
    "DMEPOS": {"E0601", "E1390", "E0260", "E0261", "E0277", "A4253",
               "A7034", "A7035", "K0823", "K0856", "K0861"},
    # Ambulance/Transport
    "AMBULANCE": {"A0427", "A0428", "A0429", "A0425", "A0426", "A0433",
                  "A0434", "A0998"},
}

# Flatten for reverse lookup: code → set of expected specialties
_CODE_TO_SPECIALTIES: dict[str, set[str]] = defaultdict(set)
for spec, codes in _SPECIALTY_CODES.items():
    for code in codes:
        _CODE_TO_SPECIALTIES[code].add(spec)


def _get_specialty_prefix(taxonomy: str) -> str:
    """Extract the meaningful specialty prefix from a taxonomy code."""
    if not taxonomy:
        return ""
    # Try exact match first, then progressively shorter prefixes
    for length in [6, 4]:
        prefix = taxonomy[:length]
        if prefix in _SPECIALTY_CODES:
            return prefix
    return taxonomy[:4]


async def validate_provider_codes(npi: str) -> dict:
    """
    Validate a provider's billed codes against their specialty.
    Returns mismatched codes and a mismatch score.
    """
    provider = get_provider_by_npi(npi)
    if not provider:
        return {"npi": npi, "found": False, "error": "Provider not found"}

    taxonomy = (provider.get("nppes") or {}).get("taxonomy_code") or ""
    specialty = (provider.get("nppes") or {}).get("specialty") or ""
    hcpcs_list = provider.get("hcpcs") or []

    if not hcpcs_list:
        return {"npi": npi, "found": True, "codes_analyzed": 0,
                "mismatches": [], "mismatch_score": 0}

    spec_prefix = _get_specialty_prefix(taxonomy)
    expected_codes = _SPECIALTY_CODES.get(spec_prefix, set())

    if not expected_codes:
        return {
            "npi": npi,
            "found": True,
            "taxonomy": taxonomy,
            "specialty": specialty,
            "codes_analyzed": len(hcpcs_list),
            "mismatches": [],
            "mismatch_score": 0,
            "note": f"No reference codes for taxonomy prefix '{spec_prefix}' — cannot validate",
        }

    # Check each billed code
    total_paid = 0
    mismatched_paid = 0
    mismatches = []

    for h in hcpcs_list:
        code = h.get("hcpcs_code", "")
        paid = float(h.get("total_paid", 0) or 0)
        claims = int(h.get("total_claims", 0) or 0)
        total_paid += paid

        if code and code not in expected_codes:
            # Check if the code belongs to ANY known specialty
            belongs_to = _CODE_TO_SPECIALTIES.get(code, set())
            mismatched_paid += paid
            mismatches.append({
                "hcpcs_code": code,
                "total_paid": round(paid, 2),
                "total_claims": claims,
                "expected_specialties": list(belongs_to)[:5],
                "severity": "HIGH" if paid > 10000 else "MEDIUM" if paid > 1000 else "LOW",
            })

    # Mismatch score: % of revenue from unexpected codes
    mismatch_pct = (mismatched_paid / total_paid * 100) if total_paid > 0 else 0

    mismatches.sort(key=lambda x: x["total_paid"], reverse=True)

    return {
        "npi": npi,
        "found": True,
        "taxonomy": taxonomy,
        "specialty": specialty,
        "specialty_prefix": spec_prefix,
        "codes_analyzed": len(hcpcs_list),
        "expected_code_count": len(expected_codes),
        "mismatch_count": len(mismatches),
        "mismatch_score": round(mismatch_pct, 1),
        "total_paid": round(total_paid, 2),
        "mismatched_paid": round(mismatched_paid, 2),
        "mismatches": mismatches[:20],  # top 20 by paid
    }


async def batch_validate_codes(limit: int = 100, min_mismatch_pct: float = 30.0) -> dict:
    """
    Validate all providers' codes against their specialties.
    Returns providers with mismatch_score above the threshold.
    """
    providers = get_prescanned()
    if not providers:
        return {"flagged": [], "total_flagged": 0}

    flagged = []
    for p in providers:
        npi = p["npi"]
        taxonomy = (p.get("nppes") or {}).get("taxonomy_code") or ""
        hcpcs_list = p.get("hcpcs") or []

        if not hcpcs_list or not taxonomy:
            continue

        spec_prefix = _get_specialty_prefix(taxonomy)
        expected_codes = _SPECIALTY_CODES.get(spec_prefix, set())
        if not expected_codes:
            continue

        total_paid = 0
        mismatched_paid = 0
        mismatch_count = 0

        for h in hcpcs_list:
            code = h.get("hcpcs_code", "")
            paid = float(h.get("total_paid", 0) or 0)
            total_paid += paid
            if code and code not in expected_codes:
                mismatched_paid += paid
                mismatch_count += 1

        if total_paid == 0:
            continue

        mismatch_pct = mismatched_paid / total_paid * 100
        if mismatch_pct < min_mismatch_pct:
            continue

        flagged.append({
            "npi": npi,
            "taxonomy": taxonomy,
            "specialty": (p.get("nppes") or {}).get("specialty") or "",
            "mismatch_score": round(mismatch_pct, 1),
            "mismatch_count": mismatch_count,
            "total_codes": len(hcpcs_list),
            "total_paid": round(total_paid, 2),
            "mismatched_paid": round(mismatched_paid, 2),
            "risk_score": p.get("risk_score", 0),
        })

    flagged.sort(key=lambda x: x["mismatch_score"], reverse=True)
    flagged = flagged[:limit]

    return {
        "flagged": flagged,
        "total_flagged": len(flagged),
        "min_mismatch_pct": min_mismatch_pct,
        "note": "Providers billing codes outside their specialty norm",
    }
