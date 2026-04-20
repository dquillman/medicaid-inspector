"""
Medicaid enrollment data store — state-level enrollment counts.

Fetches from CMS T-MSIS enrollment API on demand, with hardcoded
2023 fallback estimates (sourced from KFF/CMS reporting).
Cached to disk at backend/enrollment_cache.json.
"""
import json
import logging
import pathlib
import time
from typing import Optional

log = logging.getLogger(__name__)

_CACHE_FILE = pathlib.Path(__file__).parent.parent / "enrollment_cache.json"
_CMS_API_URL = "https://data.medicaid.gov/api/1/datastore/query/6165f45b-ca93-5bb5-9d06-db29c2a48e58/0"

# In-memory store: { "CA": 14700000, "NY": 7900000, ... }
_enrollment: dict[str, int] = {}

# Hardcoded 2023 Medicaid enrollment estimates by state (approximate, in thousands)
# Sources: KFF, CMS monthly enrollment reports
_FALLBACK_ENROLLMENT: dict[str, int] = {
    "AL": 1_130_000,
    "AK": 280_000,
    "AZ": 2_400_000,
    "AR": 1_050_000,
    "CA": 14_700_000,
    "CO": 1_700_000,
    "CT": 1_100_000,
    "DE": 310_000,
    "DC": 290_000,
    "FL": 5_000_000,
    "GA": 2_300_000,
    "HI": 420_000,
    "ID": 470_000,
    "IL": 3_600_000,
    "IN": 1_900_000,
    "IA": 900_000,
    "KS": 480_000,
    "KY": 1_600_000,
    "LA": 1_800_000,
    "ME": 430_000,
    "MD": 1_700_000,
    "MA": 2_300_000,
    "MI": 3_000_000,
    "MN": 1_400_000,
    "MS": 780_000,
    "MO": 1_300_000,
    "MT": 330_000,
    "NE": 380_000,
    "NV": 900_000,
    "NH": 240_000,
    "NJ": 2_400_000,
    "NM": 900_000,
    "NY": 7_900_000,
    "NC": 2_700_000,
    "ND": 120_000,
    "OH": 3_400_000,
    "OK": 1_200_000,
    "OR": 1_500_000,
    "PA": 3_600_000,
    "RI": 370_000,
    "SC": 1_300_000,
    "SD": 150_000,
    "TN": 1_800_000,
    "TX": 5_500_000,
    "UT": 500_000,
    "VT": 200_000,
    "VA": 2_000_000,
    "WA": 2_400_000,
    "WV": 600_000,
    "WI": 1_500_000,
    "WY": 80_000,
}


def get_enrollment() -> dict[str, int]:
    """Return the current enrollment data (state -> count)."""
    return dict(_enrollment)


def set_enrollment(data: dict[str, int]) -> None:
    """Replace in-memory enrollment data and persist to disk."""
    global _enrollment
    _enrollment = dict(data)
    _save_to_disk()


def load_enrollment_from_disk() -> bool:
    """Load enrollment from disk cache. Returns True if cache existed."""
    global _enrollment
    if not _CACHE_FILE.exists():
        return False
    try:
        raw = json.loads(_CACHE_FILE.read_text())
        _enrollment = raw.get("enrollment", {})
        log.info("Loaded enrollment data for %d states from disk cache", len(_enrollment))
        return bool(_enrollment)
    except Exception as e:
        log.warning("Failed to load enrollment cache: %s", e)
        return False


def _save_to_disk() -> None:
    """Persist enrollment data to JSON file."""
    try:
        _CACHE_FILE.write_text(json.dumps({
            "enrollment": _enrollment,
            "updated_at": time.time(),
        }, indent=2))
        log.info("Saved enrollment data for %d states to disk", len(_enrollment))
    except Exception as e:
        log.warning("Failed to save enrollment cache: %s", e)


async def fetch_enrollment_data() -> dict[str, int]:
    """
    Try to fetch enrollment data from CMS T-MSIS API.
    Falls back to hardcoded 2023 estimates if API is unavailable.
    Returns state -> enrollment count mapping.
    """
    import httpx

    try:
        log.info("Fetching CMS T-MSIS enrollment data...")
        async with httpx.AsyncClient(timeout=30) as client:
            # The CMS datastore API supports limit/offset queries
            # We request state-level aggregates
            resp = await client.get(_CMS_API_URL, params={
                "limit": 500,
                "offset": 0,
            })
            resp.raise_for_status()
            data = resp.json()

            results: dict[str, int] = {}
            rows = data.get("results", [])

            if not rows:
                log.warning("CMS API returned no rows — using fallback data")
                return dict(_FALLBACK_ENROLLMENT)

            # Try to parse state and enrollment from the response
            # T-MSIS schema varies; look for common field names
            for row in rows:
                state = (
                    row.get("state_abbreviation")
                    or row.get("state")
                    or row.get("state_code")
                    or ""
                )
                enrollment = (
                    row.get("total_medicaid_enrollment")
                    or row.get("enrollment")
                    or row.get("total_enrollment")
                    or row.get("medicaid_enrollment")
                    or 0
                )

                if state and len(state) == 2 and enrollment:
                    state = state.upper()
                    count = int(float(enrollment))
                    # Keep the highest value per state (in case of multiple rows)
                    if count > results.get(state, 0):
                        results[state] = count

            if len(results) >= 10:
                log.info("Fetched enrollment data for %d states from CMS API", len(results))
                # Fill in any missing states from fallback
                for st, count in _FALLBACK_ENROLLMENT.items():
                    if st not in results:
                        results[st] = count
                return results
            else:
                log.warning("CMS API returned only %d states — using fallback", len(results))
                return dict(_FALLBACK_ENROLLMENT)

    except Exception as e:
        log.warning("CMS enrollment API unavailable (%s) — using hardcoded 2023 estimates", e)
        return dict(_FALLBACK_ENROLLMENT)


async def load_or_fetch_enrollment() -> None:
    """Load enrollment from disk, or fetch from CMS API if not cached."""
    if load_enrollment_from_disk():
        return
    data = await fetch_enrollment_data()
    set_enrollment(data)
