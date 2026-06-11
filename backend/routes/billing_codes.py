"""
Billing Code Search — find providers who bill specific HCPCS/CPT codes.

Strategy: the slim prescan cache does not carry per-HCPCS breakdowns
(per-provider hcpcs arrays were dropped to keep the file at 59 MB), so
when those arrays are absent we fall back to a DuckDB query against the
Parquet dataset and enrich each row with the provider's name/state/
risk_score from the slim cache. Responses are cached for 10 minutes.
"""
import pathlib as _pathlib
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.store import get_prescanned
from data.cpt_descriptions import CPT_DESCRIPTIONS
from data.duckdb_client import get_parquet_path, query_async
from data.icd10_descriptions import ICD10_DESCRIPTIONS, HCPCS_TO_ICD10
from routes.auth import require_user

# Workstation-generated (npi, code, paid, claims) aggregate, code-sorted —
# see scripts/precompute_analyses.py. Synced from GCS at startup. Column
# names match the big dataset parquet so the SQL below runs unchanged;
# querying this ~50 MB local file takes milliseconds vs 30-180s against the
# remote 2.94 GB parquet (which 503s the per-code search on Cloud Run).
_HCPCS_INDEX = _pathlib.Path(__file__).parent.parent / "hcpcs_index.parquet"


def _search_parquet() -> str:
    """Path for per-code SQL: the local HCPCS index when present, else the dataset parquet."""
    if _HCPCS_INDEX.exists() and _HCPCS_INDEX.stat().st_size > 1_000:
        return str(_HCPCS_INDEX).replace("\\", "/")
    return get_parquet_path()

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


def _has_hcpcs_in_cache() -> bool:
    """True if at least one provider in the cache carries a populated hcpcs list.

    Used to decide whether to use the in-memory path (full cache) or fall back
    to DuckDB-on-demand (slim cache).
    """
    from services.slim_cache_enricher import has_hcpcs_detail
    return has_hcpcs_detail()


def _npi_enrichment_map() -> dict[str, dict]:
    """Lookup of {npi: {provider_name, provider_type, state, risk_score}} from the cache."""
    out: dict[str, dict] = {}
    for p in get_prescanned():
        npi = p.get("npi")
        if not npi:
            continue
        out[npi] = {
            "provider_name": p.get("provider_name", ""),
            "provider_type": p.get("provider_type", ""),
            "state": p.get("state", ""),
            "risk_score": p.get("risk_score", 0),
        }
    return out


# ── DuckDB-backed query helpers (used when slim cache lacks hcpcs detail) ────


async def _ddb_providers_by_code(code: str, limit: int) -> list[dict]:
    """Aggregate per-NPI spend on a single HCPCS code via DuckDB."""
    sql = f"""
    SELECT
        BILLING_PROVIDER_NPI_NUM        AS npi,
        SUM(TOTAL_PAID)                 AS total_paid,
        SUM(TOTAL_CLAIMS)               AS total_claims
    FROM read_parquet('{_search_parquet()}')
    WHERE UPPER(HCPCS_CODE) = ?
    GROUP BY npi
    ORDER BY total_paid DESC
    LIMIT ?
    """
    return await query_async(sql, (code, limit))


async def _ddb_top_codes(limit: int, min_providers: int) -> list[dict]:
    """Rank HCPCS codes by total paid across providers."""
    sql = f"""
    SELECT
        UPPER(HCPCS_CODE)                            AS code,
        COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM)     AS provider_count,
        SUM(TOTAL_PAID)                              AS total_paid,
        SUM(TOTAL_CLAIMS)                            AS total_claims
    FROM read_parquet('{_search_parquet()}')
    WHERE HCPCS_CODE IS NOT NULL
    GROUP BY UPPER(HCPCS_CODE)
    HAVING provider_count >= ?
    ORDER BY total_paid DESC
    LIMIT ?
    """
    return await query_async(sql, (min_providers, limit))


async def _ddb_providers_by_codes(codes: list[str]) -> list[dict]:
    """Per-NPI per-code spend for the given HCPCS codes."""
    placeholders = ", ".join("?" for _ in codes)
    sql = f"""
    SELECT
        BILLING_PROVIDER_NPI_NUM        AS npi,
        UPPER(HCPCS_CODE)               AS hcpcs_code,
        SUM(TOTAL_PAID)                 AS total_paid,
        SUM(TOTAL_CLAIMS)               AS total_claims
    FROM read_parquet('{_search_parquet()}')
    WHERE UPPER(HCPCS_CODE) IN ({placeholders})
    GROUP BY npi, hcpcs_code
    """
    return await query_async(sql, tuple(codes))


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

    matches: list[dict] = []
    if _has_hcpcs_in_cache():
        for p in get_prescanned():
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
    else:
        rows = await _ddb_providers_by_code(code, limit * 2)  # pull extra for stable ranking
        enrich = _npi_enrichment_map()
        for r in rows:
            npi = r["npi"]
            meta = enrich.get(npi, {})
            matches.append({
                "npi": npi,
                "provider_name": meta.get("provider_name", ""),
                "provider_type": meta.get("provider_type", ""),
                "state": meta.get("state", ""),
                "risk_score": meta.get("risk_score", 0),
                "total_paid": r["total_paid"] or 0,
                "total_claims": r["total_claims"] or 0,
                "code_rank": None,  # would require a per-NPI HCPCS ordering query — omitted in DDB path
                "total_codes_billed": None,
            })

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

    results: list[dict] = []
    if _has_hcpcs_in_cache():
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

        for stats in code_stats.values():
            if stats["provider_count"] < min_providers:
                continue
            stats["avg_risk_score"] = round(
                stats["avg_risk_score_sum"] / stats["provider_count"], 1
            )
            del stats["avg_risk_score_sum"]
            results.append(stats)
    else:
        from services.slim_cache_enricher import parquet_is_local
        from services.precomputed_store import get_precomputed
        pre = get_precomputed("billing_top_codes")
        if pre:
            results = [dict(c) for c in (pre.get("codes") or [])
                       if c.get("provider_count", 0) >= min_providers]
        elif not parquet_is_local():
            # No precomputed data and the remote-parquet query would trip the
            # Cloud Run timeout — return empty rather than hang.
            results = []
        else:
            rows = await _ddb_top_codes(limit, min_providers)
            # avg_risk_score requires per-NPI scores, which DuckDB doesn't have —
            # leave as 0 in DDB path (the slim cache can't compute it without HCPCS rosters)
            for r in rows:
                results.append({
                    "code": r["code"],
                    "provider_count": r["provider_count"],
                    "total_paid": r["total_paid"] or 0,
                    "total_claims": r["total_claims"] or 0,
                    "avg_risk_score": 0.0,
                })

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

    matches: list[dict] = []
    if _has_hcpcs_in_cache():
        for p in get_prescanned():
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
    else:
        rows = await _ddb_providers_by_codes(sorted(code_set))
        # Group rows by NPI so we can apply ANY/ALL logic
        by_npi: dict[str, list[dict]] = {}
        for r in rows:
            by_npi.setdefault(r["npi"], []).append(r)
        enrich = _npi_enrichment_map()
        for npi, code_rows in by_npi.items():
            matched_codes = {r["hcpcs_code"] for r in code_rows}
            if logic == "all" and matched_codes != code_set:
                continue
            # ANY path: matched_codes guaranteed non-empty since rows exist
            meta = enrich.get(npi, {})
            code_details = [
                {
                    "code": r["hcpcs_code"],
                    "total_paid": r["total_paid"] or 0,
                    "total_claims": r["total_claims"] or 0,
                }
                for r in code_rows
            ]
            matches.append({
                "npi": npi,
                "provider_name": meta.get("provider_name", ""),
                "provider_type": meta.get("provider_type", ""),
                "state": meta.get("state", ""),
                "risk_score": meta.get("risk_score", 0),
                "matched_codes": code_details,
                "total_paid_matched": sum(c["total_paid"] for c in code_details),
                "total_claims_matched": sum(c["total_claims"] for c in code_details),
                "codes_matched": len(matched_codes),
                "total_codes_billed": None,
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


def _build_diag_flag_for_provider(npi: str, name: str, state: str, risk_score: float,
                                  code_rows: list[dict]) -> dict | None:
    """Shared scoring loop used by both the cache- and DuckDB-backed code paths."""
    provider_issues = []
    for r in code_rows:
        code = r["hcpcs_code"].upper() if r.get("hcpcs_code") else ""
        if code not in _HCPCS_CATEGORIES:
            continue
        for rule in _HCPCS_CATEGORIES[code]:
            expected_icd = HCPCS_TO_ICD10.get(code, [])
            valid_prefixes = rule["valid_icd_prefixes"]
            matching = sum(
                1 for icd in expected_icd
                if any(icd.startswith(pfx) for pfx in valid_prefixes)
            )
            if expected_icd and matching == 0:
                paid = r.get("total_paid", 0) or 0
                claims = r.get("total_claims", 0) or 0
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
    if not provider_issues:
        return None
    return {
        "npi": npi,
        "provider_name": name,
        "state": state,
        "risk_score": risk_score,
        "issues": provider_issues,
        "issue_count": len(provider_issues),
        "total_flagged_paid": round(sum(i["total_paid"] for i in provider_issues), 2),
    }


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

    flagged: list[dict] = []
    category_counts: dict[str, int] = {}

    if _has_hcpcs_in_cache():
        for p in get_prescanned():
            entry = _build_diag_flag_for_provider(
                p.get("npi", ""),
                p.get("provider_name", ""),
                p.get("state", ""),
                p.get("risk_score", 0),
                p.get("hcpcs") or [],
            )
            if entry:
                flagged.append(entry)
                for iss in entry["issues"]:
                    category_counts[iss["category"]] = category_counts.get(iss["category"], 0) + 1
    else:
        from services.slim_cache_enricher import parquet_is_local, SLIM_REMOTE_NOTE
        from services.precomputed_store import get_precomputed
        pre = get_precomputed("billing_diagnosis_flags")
        if pre:
            response = dict(pre)
            response["flagged_providers"] = (pre.get("flagged_providers") or [])[:limit]
            _cache_set(cache_key, response)
            return response
        if not parquet_is_local():
            # Remote-parquet query would trip the Cloud Run timeout — degrade clearly.
            response = {"flagged_providers": [], "total": 0, "category_counts": {},
                        "note": SLIM_REMOTE_NOTE}
            _cache_set(cache_key, response)
            return response
        # DuckDB: only pull rows for the small set of HCPCS codes in our category rules
        all_rule_codes = sorted(_HCPCS_CATEGORIES.keys())
        placeholders = ", ".join("?" for _ in all_rule_codes)
        sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM        AS npi,
            UPPER(HCPCS_CODE)               AS hcpcs_code,
            SUM(TOTAL_PAID)                 AS total_paid,
            SUM(TOTAL_CLAIMS)               AS total_claims
        FROM read_parquet('{_search_parquet()}')
        WHERE UPPER(HCPCS_CODE) IN ({placeholders})
        GROUP BY npi, hcpcs_code
        """
        rows = await query_async(sql, tuple(all_rule_codes))
        by_npi: dict[str, list[dict]] = {}
        for r in rows:
            by_npi.setdefault(r["npi"], []).append(r)
        enrich = _npi_enrichment_map()
        for npi, code_rows in by_npi.items():
            meta = enrich.get(npi, {})
            entry = _build_diag_flag_for_provider(
                npi,
                meta.get("provider_name", ""),
                meta.get("state", ""),
                meta.get("risk_score", 0),
                code_rows,
            )
            if entry:
                flagged.append(entry)
                for iss in entry["issues"]:
                    category_counts[iss["category"]] = category_counts.get(iss["category"], 0) + 1

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
