"""
CMS Medicare Physician & Other Practitioners - by Provider (MUP) client.

Joins to the Medicaid spending dataset on NPI to surface per-provider
diagnosis-mix (chronic-condition prevalence) and beneficiary demographics
that the Medicaid Parquet doesn't carry.

Public dataset, no auth. Updated annually by CMS. Data year is 2023.
Source: https://data.cms.gov/provider-summary-by-type-of-service/medicare-physician-other-practitioners/medicare-physician-other-practitioners-by-provider
"""
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_DATASET_ID = "8889d81e-2ee7-448f-8713-f071038289b5"
_API_URL = f"https://data.cms.gov/data-api/v1/dataset/{_DATASET_ID}/data"

# In-memory cache: NPI -> (timestamp, row-or-None)
# MUP data is annual; a 24h TTL is generous and keeps the dashboard snappy.
_CACHE: dict[str, tuple[float, Optional[dict]]] = {}
_TTL_SECONDS = 24 * 3600


# The 25 Bene_CC_*_Pct columns expressed as a label map for the UI.
CHRONIC_CONDITION_LABELS: dict[str, str] = {
    "Bene_CC_BH_ADHD_OthCD_V1_Pct":     "ADHD / Other Conduct Disorders",
    "Bene_CC_BH_Alcohol_Drug_V1_Pct":   "Alcohol & Drug Use Disorder",
    "Bene_CC_BH_Tobacco_V1_Pct":        "Tobacco Use Disorder",
    "Bene_CC_BH_Alz_NonAlzdem_V2_Pct":  "Alzheimer's / Non-Alzheimer Dementia",
    "Bene_CC_BH_Anxiety_V1_Pct":        "Anxiety Disorders",
    "Bene_CC_BH_Bipolar_V1_Pct":        "Bipolar Disorder",
    "Bene_CC_BH_Mood_V2_Pct":           "Mood Disorders (other)",
    "Bene_CC_BH_Depress_V1_Pct":        "Depression",
    "Bene_CC_BH_PD_V1_Pct":             "Personality Disorders",
    "Bene_CC_BH_PTSD_V1_Pct":           "PTSD",
    "Bene_CC_BH_Schizo_OthPsy_V1_Pct":  "Schizophrenia / Other Psychotic Disorders",
    "Bene_CC_PH_Asthma_V2_Pct":         "Asthma",
    "Bene_CC_PH_Afib_V2_Pct":           "Atrial Fibrillation",
    "Bene_CC_PH_Cancer6_V2_Pct":        "Cancer (6 common)",
    "Bene_CC_PH_CKD_V2_Pct":            "Chronic Kidney Disease",
    "Bene_CC_PH_COPD_V2_Pct":           "COPD",
    "Bene_CC_PH_Diabetes_V2_Pct":       "Diabetes",
    "Bene_CC_PH_HF_NonIHD_V2_Pct":      "Heart Failure (non-IHD)",
    "Bene_CC_PH_Hyperlipidemia_V2_Pct": "Hyperlipidemia",
    "Bene_CC_PH_Hypertension_V2_Pct":   "Hypertension",
    "Bene_CC_PH_IschemicHeart_V2_Pct":  "Ischemic Heart Disease",
    "Bene_CC_PH_Osteoporosis_V2_Pct":   "Osteoporosis",
    "Bene_CC_PH_Parkinson_V2_Pct":      "Parkinson's Disease",
    "Bene_CC_PH_Arthritis_V2_Pct":      "Rheumatoid Arthritis / Osteoarthritis",
    "Bene_CC_PH_Stroke_TIA_V2_Pct":     "Stroke / TIA",
}


def _is_fresh(entry: tuple[float, Optional[dict]]) -> bool:
    return (time.time() - entry[0]) < _TTL_SECONDS


async def fetch_provider(npi: str) -> Optional[dict]:
    """Fetch one MUP row for an NPI. Returns None if not in Medicare data.

    Resolution order:
      1. In-memory LRU cache (24h TTL)
      2. Local parquet cache (mup_cache.lookup) — populated by /api/admin/mup-refresh
      3. Live CMS data API (fallback when no local cache)
    """
    if npi in _CACHE and _is_fresh(_CACHE[npi]):
        return _CACHE[npi][1]

    # Local cache hit — synchronous, no HTTP
    try:
        from services import mup_cache
        if mup_cache.is_local():
            row = mup_cache.lookup(npi)
            _CACHE[npi] = (time.time(), row)
            return row
    except Exception as e:
        log.debug("[mup_client] Local cache lookup skipped: %s", e)

    # Fall back to live API
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_API_URL, params={"filter[Rndrng_NPI]": npi, "size": 1})
            resp.raise_for_status()
            rows = resp.json()
            row = rows[0] if isinstance(rows, list) and rows else None
            _CACHE[npi] = (time.time(), row)
            return row
    except Exception as e:
        log.warning("[mup_client] Fetch failed for NPI=%s: %s", npi, e)
        return None


def lookup_sync(npi: str) -> Optional[dict]:
    """Synchronous local-cache-only lookup. Returns None if cache missing or
    the NPI isn't present. Used by the batch scanner where async/HTTP fallback
    would slow scans to a crawl."""
    if npi in _CACHE and _is_fresh(_CACHE[npi]):
        return _CACHE[npi][1]
    try:
        from services import mup_cache
        if not mup_cache.is_local():
            return None
        row = mup_cache.lookup(npi)
        _CACHE[npi] = (time.time(), row)
        return row
    except Exception:
        return None


def _pct(row: dict, key: str) -> Optional[float]:
    raw = row.get(key)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def extract_diagnosis_mix(row: dict) -> list[dict]:
    """Pull the 25 Bene_CC_*_Pct columns into a sorted, labeled list."""
    out: list[dict] = []
    for col, label in CHRONIC_CONDITION_LABELS.items():
        pct = _pct(row, col)
        if pct is None:
            continue
        out.append({"column": col, "label": label, "pct": pct})
    out.sort(key=lambda r: r["pct"] or 0, reverse=True)
    return out


def summarize_provider(row: dict) -> dict:
    """Shape an MUP row for the API response."""
    def _i(k: str) -> Optional[int]:
        v = row.get(k)
        if v in (None, ""):
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    return {
        "npi": row.get("Rndrng_NPI"),
        "provider_type": row.get("Rndrng_Prvdr_Type"),
        "specialty_state": row.get("Rndrng_Prvdr_State_Abrvtn"),
        "credentials": row.get("Rndrng_Prvdr_Crdntls"),
        "entity_code": row.get("Rndrng_Prvdr_Ent_Cd"),
        "city": row.get("Rndrng_Prvdr_City"),
        "zip5": row.get("Rndrng_Prvdr_Zip5"),
        "tot_benes": _i("Tot_Benes"),
        "bene_avg_age": _pct(row, "Bene_Avg_Age"),
        "bene_avg_risk_score": _pct(row, "Bene_Avg_Risk_Scre"),
        "dual_eligible_cnt": _i("Bene_Dual_Cnt"),
        "diagnosis_mix": extract_diagnosis_mix(row),
        "data_source": "CMS MUP-by-Provider (Medicare 2023)",
    }
