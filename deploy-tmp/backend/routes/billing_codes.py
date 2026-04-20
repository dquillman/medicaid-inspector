"""
Billing Code Search — find providers who bill specific HCPCS/CPT codes.
Uses the in-memory prescan cache (no Parquet queries).
"""
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.store import get_prescanned
from data.cpt_descriptions import CPT_DESCRIPTIONS
from data.icd10_descriptions import ICD10_DESCRIPTIONS, HCPCS_TO_ICD10
from routes.auth import require_user

router = APIRouter(
    prefix="/api/billing-codes",
    tags=["billing-codes"],
    dependencies=[Depends(require_user)],
)

# ── Cache (10 min TTL) ───────────────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 600


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (_time.time(), value)


@router.get("/search")
async def search_by_code(
    code: str = Query(..., min_length=1, max_length=10, description="HCPCS/CPT code"),
    limit: int = Query(100, ge=1, le=500),
):
    """Find all providers who bill a specific HCPCS/CPT code, ranked by total paid."""
    code = code.strip().upper()
    cache_key = f"code_search:{code}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    providers = get_prescanned()
    matches = []

    for p in providers:
        hcpcs_list = p.get("hcpcs") or []
        for h in hcpcs_list:
            if h.get("hcpcs_code", "").upper() == code:
                matches.append({
                    "npi": p.get("npi", ""),
                    "provider_name": p.get("provider_name", ""),
                    "provider_type": p.get("provider_type", ""),
                    "state": p.get("state", ""),
                    "risk_score": p.get("risk_score", 0),
                    "total_paid": h.get("total_paid", 0),
                    "total_claims": h.get("total_claims", 0),
                    "code_rank": next(
                        (i + 1 for i, x in enumerate(hcpcs_list) if x.get("hcpcs_code", "").upper() == code),
                        None,
                    ),
                    "total_codes_billed": len(hcpcs_list),
                })
                break

    matches.sort(key=lambda x: x["total_paid"], reverse=True)
    total = len(matches)
    matches = matches[:limit]

    response = {
        "code": code,
        "total_providers": total,
        "providers": matches,
        "stats": {
            "total_paid_all": sum(m["total_paid"] for m in matches),
            "total_claims_all": sum(m["total_claims"] for m in matches),
            "avg_paid": sum(m["total_paid"] for m in matches) / len(matches) if matches else 0,
            "avg_risk_score": sum(m["risk_score"] for m in matches) / len(matches) if matches else 0,
            "high_risk_count": sum(1 for m in matches if m["risk_score"] >= 60),
        },
    }
    _cache_set(cache_key, response)
    return response


@router.get("/top-codes")
async def top_codes(
    limit: int = Query(50, ge=1, le=200),
    min_providers: int = Query(3, ge=1, le=100),
):
    """List the most commonly billed HCPCS/CPT codes across all scanned providers."""
    cache_key = f"top_codes:{limit}:{min_providers}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    providers = get_prescanned()
    code_stats: dict[str, dict] = {}

    for p in providers:
        hcpcs_list = p.get("hcpcs") or []
        for h in hcpcs_list:
            c = h.get("hcpcs_code", "").upper()
            if not c:
                continue
            if c not in code_stats:
                code_stats[c] = {
                    "code": c,
                    "provider_count": 0,
                    "total_paid": 0,
                    "total_claims": 0,
                    "avg_risk_score_sum": 0,
                }
            code_stats[c]["provider_count"] += 1
            code_stats[c]["total_paid"] += h.get("total_paid", 0)
            code_stats[c]["total_claims"] += h.get("total_claims", 0)
            code_stats[c]["avg_risk_score_sum"] += p.get("risk_score", 0)

    results = []
    for stats in code_stats.values():
        if stats["provider_count"] < min_providers:
            continue
        stats["avg_risk_score"] = round(
            stats["avg_risk_score_sum"] / stats["provider_count"], 1
        )
        del stats["avg_risk_score_sum"]
        results.append(stats)

    results.sort(key=lambda x: x["total_paid"], reverse=True)
    results = results[:limit]

    response = {
        "total_codes": len(results),
        "codes": results,
    }
    _cache_set(cache_key, response)
    return response


@router.get("/providers-by-codes")
async def providers_by_codes(
    codes: str = Query(..., description="Comma-separated HCPCS/CPT codes"),
    logic: str = Query("any", pattern="^(any|all)$", description="'any' = billed at least one, 'all' = billed every code"),
    limit: int = Query(100, ge=1, le=500),
):
    """Find providers who bill one or more specified codes. Supports AND/OR logic."""
    code_set = {c.strip().upper() for c in codes.split(",") if c.strip()}
    if not code_set:
        return {"providers": [], "total_providers": 0, "codes": []}

    cache_key = f"multi_code:{','.join(sorted(code_set))}:{logic}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    providers = get_prescanned()
    matches = []

    for p in providers:
        hcpcs_list = p.get("hcpcs") or []
        provider_codes = {h.get("hcpcs_code", "").upper() for h in hcpcs_list}
        matched_codes = code_set & provider_codes

        if logic == "all" and matched_codes != code_set:
            continue
        if logic == "any" and not matched_codes:
            continue

        code_details = []
        total_paid_matched = 0
        total_claims_matched = 0
        for h in hcpcs_list:
            if h.get("hcpcs_code", "").upper() in code_set:
                code_details.append({
                    "code": h["hcpcs_code"],
                    "total_paid": h.get("total_paid", 0),
                    "total_claims": h.get("total_claims", 0),
                })
                total_paid_matched += h.get("total_paid", 0)
                total_claims_matched += h.get("total_claims", 0)

        matches.append({
            "npi": p.get("npi", ""),
            "provider_name": p.get("provider_name", ""),
            "provider_type": p.get("provider_type", ""),
            "state": p.get("state", ""),
            "risk_score": p.get("risk_score", 0),
            "matched_codes": code_details,
            "total_paid_matched": total_paid_matched,
            "total_claims_matched": total_claims_matched,
            "codes_matched": len(matched_codes),
            "total_codes_billed": len(hcpcs_list),
        })

    matches.sort(key=lambda x: x["total_paid_matched"], reverse=True)
    total = len(matches)
    matches = matches[:limit]

    response = {
        "codes_searched": sorted(code_set),
        "logic": logic,
        "total_providers": total,
        "providers": matches,
    }
    _cache_set(cache_key, response)
    return response


@router.get("/diagnoses/{code}")
async def diagnoses_for_code(code: str):
    """Return common ICD-10 diagnoses associated with a HCPCS/CPT code."""
    code = code.strip().upper()
    cpt_desc = CPT_DESCRIPTIONS.get(code, "")
    icd_codes = HCPCS_TO_ICD10.get(code, [])

    diagnoses = []
    for icd in icd_codes:
        desc = ICD10_DESCRIPTIONS.get(icd, "")
        diagnoses.append({
            "icd10": icd,
            "description": desc or f"ICD-10 code {icd}",
        })

    return {
        "hcpcs_code": code,
        "hcpcs_description": cpt_desc,
        "diagnoses": diagnoses,
        "total": len(diagnoses),
        "has_crosswalk": len(icd_codes) > 0,
    }


@router.get("/icd10/search")
async def search_icd10(
    q: str = Query(..., min_length=1, max_length=50, description="ICD-10 code or keyword"),
    limit: int = Query(30, ge=1, le=100),
):
    """Search ICD-10 codes by code prefix or description keyword."""
    q_upper = q.strip().upper()
    q_lower = q.strip().lower()
    results = []

    for code, desc in ICD10_DESCRIPTIONS.items():
        if code.upper().startswith(q_upper) or q_lower in desc.lower():
            results.append({"icd10": code, "description": desc})
            if len(results) >= limit:
                break

    return {"query": q, "results": results, "total": len(results)}


# ── Diagnosis-Billing Code Mismatch Detection ──────────────────────────────

# Category mappings: which ICD-10 prefixes are valid for which HCPCS categories
_CATEGORY_RULES: dict[str, dict] = {
    # Mental health procedure codes should have F-codes
    "psych": {
        "hcpcs": ["90791", "90792", "90832", "90833", "90834", "90836", "90837", "90838",
                   "90839", "90840", "90845", "90846", "90847", "90849", "90853",
                   "H0001", "H0004", "H0005", "H0015", "H0020"],
        "valid_icd_prefixes": ["F"],
        "label": "Mental Health",
        "issue": "Mental health procedure billed without mental health diagnosis",
    },
    # Diabetes supplies/drugs should have E10/E11/E13
    "diabetes": {
        "hcpcs": ["A4253", "A4259", "E1390", "J1100", "J0129", "J2794",
                   "82947", "83036"],
        "valid_icd_prefixes": ["E10", "E11", "E13", "R73", "Z13.1", "Z79.4"],
        "label": "Diabetes",
        "issue": "Diabetes-related billing without diabetes diagnosis",
    },
    # CPAP/BiPAP should have sleep apnea or respiratory failure
    "sleep_respiratory": {
        "hcpcs": ["A7003", "A7034", "A7035", "A7037", "A7038",
                   "E0431", "E0439", "E0601", "E0470", "94660", "94761"],
        "valid_icd_prefixes": ["G47", "J96", "R06", "J44", "J84", "Z99.81", "Z99.89"],
        "label": "Sleep/Respiratory DME",
        "issue": "Sleep/respiratory equipment billed without qualifying diagnosis",
    },
    # Dialysis should have CKD stage 5 or ESRD
    "dialysis": {
        "hcpcs": ["90935", "90937", "90945", "90960", "90961", "90966", "90970"],
        "valid_icd_prefixes": ["N18", "N17", "N19", "Z99.2"],
        "label": "Dialysis",
        "issue": "Dialysis billed without kidney disease diagnosis",
    },
    # Oncology/chemo should have C-codes or Z51.11/Z51.12
    "oncology": {
        "hcpcs": ["96413", "96415", "96417", "J9035", "J9173", "J9264", "J9271",
                   "J9306", "J9310", "J1561", "J1569", "J1644", "J1094"],
        "valid_icd_prefixes": ["C", "D0", "Z51.11", "Z51.12"],
        "label": "Oncology/Chemotherapy",
        "issue": "Chemotherapy/oncology drug billed without cancer diagnosis",
    },
    # Wound care supplies should have wound/ulcer codes
    "wound_care": {
        "hcpcs": ["A6212", "A6216", "E0260", "E0277"],
        "valid_icd_prefixes": ["L97", "L89", "E11.621", "E11.622", "I87", "L03"],
        "label": "Wound Care",
        "issue": "Wound care supplies billed without wound/ulcer diagnosis",
    },
    # Orthopedic procedures should have M-codes or S-codes
    "ortho_joint": {
        "hcpcs": ["27447", "27130", "29881", "20610", "20611"],
        "valid_icd_prefixes": ["M", "S", "Z96"],
        "label": "Orthopedic",
        "issue": "Orthopedic procedure billed without musculoskeletal diagnosis",
    },
    # Eye surgery needs H-codes
    "ophthalmology": {
        "hcpcs": ["66984", "67028", "92014", "92004"],
        "valid_icd_prefixes": ["H"],
        "label": "Ophthalmology",
        "issue": "Eye procedure billed without ophthalmic diagnosis",
    },
    # Substance abuse treatment should have F10-F19
    "substance": {
        "hcpcs": ["99408", "99409", "J2765"],
        "valid_icd_prefixes": ["F10", "F11", "F12", "F13", "F14", "F15", "F16",
                                "F17", "F18", "F19"],
        "label": "Substance Abuse Treatment",
        "issue": "Substance abuse treatment billed without substance use disorder diagnosis",
    },
}

# Build reverse lookup: HCPCS → list of applicable category rules
_HCPCS_CATEGORIES: dict[str, list[dict]] = {}
for _cat_key, _cat_info in _CATEGORY_RULES.items():
    for _h in _cat_info["hcpcs"]:
        _HCPCS_CATEGORIES.setdefault(_h, []).append(_cat_info)


@router.get("/diagnosis-flags")
async def diagnosis_flags(limit: int = Query(100, ge=1, le=500)):
    """
    Detect providers billing specialized procedure codes that typically
    require specific diagnosis categories. Flags potential mismatches
    where a provider's billing code profile suggests possible
    diagnosis-procedure inconsistencies.
    """
    cache_key = f"diag_flags:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    providers = get_prescanned()
    flagged = []
    category_counts: dict[str, int] = {}

    for p in providers:
        hcpcs_list = p.get("hcpcs") or []
        provider_issues = []

        # Build a set of all codes this provider bills
        provider_codes = {h.get("hcpcs_code", "").upper() for h in hcpcs_list}

        for h in hcpcs_list:
            code = h.get("hcpcs_code", "").upper()
            if code not in _HCPCS_CATEGORIES:
                continue

            for rule in _HCPCS_CATEGORIES[code]:
                # Check if provider also bills related codes that validate the category
                # E.g., if billing psych codes, do they also bill E&M codes with F-prefix ICD?
                # For now: look at the crosswalk expected diagnoses
                expected_icd = HCPCS_TO_ICD10.get(code, [])
                valid_prefixes = rule["valid_icd_prefixes"]

                # Count how many expected diagnoses match the valid category
                matching = sum(
                    1 for icd in expected_icd
                    if any(icd.startswith(pfx) for pfx in valid_prefixes)
                )

                # If NONE of the crosswalk diagnoses match, this is a red flag
                if expected_icd and matching == 0:
                    paid = h.get("total_paid", 0) or 0
                    claims = h.get("total_claims", 0) or 0
                    if paid > 0:
                        expected_dx = [
                            {"icd10": icd, "description": ICD10_DESCRIPTIONS.get(icd, "")}
                            for icd in expected_icd[:3]
                        ]
                        valid_dx_examples = [
                            {"icd10": icd, "description": ICD10_DESCRIPTIONS.get(icd, "")}
                            for icd in list(ICD10_DESCRIPTIONS.keys())
                            if any(icd.startswith(pfx) for pfx in valid_prefixes)
                        ][:3]

                        provider_issues.append({
                            "hcpcs_code": code,
                            "hcpcs_description": CPT_DESCRIPTIONS.get(code, ""),
                            "category": rule["label"],
                            "issue": rule["issue"],
                            "total_paid": round(paid, 2),
                            "total_claims": claims,
                            "expected_diagnoses": expected_dx,
                            "valid_diagnoses_for_category": valid_dx_examples,
                        })
                        cat = rule["label"]
                        category_counts[cat] = category_counts.get(cat, 0) + 1

        if provider_issues:
            flagged.append({
                "npi": p.get("npi", ""),
                "provider_name": p.get("provider_name", ""),
                "state": p.get("state", ""),
                "risk_score": p.get("risk_score", 0),
                "issues": provider_issues,
                "issue_count": len(provider_issues),
                "total_flagged_paid": round(sum(i["total_paid"] for i in provider_issues), 2),
            })

    flagged.sort(key=lambda x: x["total_flagged_paid"], reverse=True)
    total = len(flagged)
    flagged = flagged[:limit]

    response = {
        "flagged_providers": flagged,
        "total": total,
        "category_counts": category_counts,
    }
    _cache_set(cache_key, response)
    return response
