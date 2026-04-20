"""
PECOS (Medicare Provider Enrollment) data store.
Downloads enrollment + reassignment data from data.cms.gov.
Provides lookups for:
- is_medicare_enrolled(npi) -> bool
- get_reassignment_groups(npi) -> list of group NPIs this individual bills through
- get_reassignment_depth(group_npi) -> how many individuals reassign to this group
- get_pecos_stats() -> summary stats

At startup: tries to load from local cache (pecos_cache.json).
If no cache, attempts to download from CMS data.cms.gov API.
All failures are non-fatal — the app works fine without PECOS data.
"""
import json
import pathlib
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

_PECOS_CACHE = pathlib.Path(__file__).parent.parent / "pecos_cache.json"

# CMS data.cms.gov JSON API endpoints (paginated, ?size=N&offset=N)
_ENROLLMENT_URL   = "https://data.cms.gov/data-api/v1/dataset/3917be29-acee-4076-af9b-089a4e3feacc/data"
_REASSIGNMENT_URL = "https://data.cms.gov/data-api/v1/dataset/26f3bdb0-2d17-4221-b1a5-b7db4b967aeb/data"

_PAGE_SIZE = 5000
_MAX_PAGES = 400  # safety cap: 5000 * 400 = 2M rows max

# ── In-memory lookups ─────────────────────────────────────────────
# Set of enrolled NPIs (10-digit strings)
_enrolled_npis: set[str] = set()

# individual NPI -> list of group NPIs they reassign billing to
_individual_to_groups: dict[str, list[str]] = {}

# group NPI -> list of individual NPIs that reassign to this group
_group_to_individuals: dict[str, list[str]] = {}

_loaded = False


# ── Disk cache ────────────────────────────────────────────────────

def load_pecos_from_disk() -> bool:
    """Try to load the cached PECOS data. Returns True if successful."""
    global _enrolled_npis, _individual_to_groups, _group_to_individuals, _loaded
    try:
        if _PECOS_CACHE.exists():
            data = json.loads(_PECOS_CACHE.read_text(encoding="utf-8"))
            _enrolled_npis = set(data.get("enrolled_npis", []))
            _individual_to_groups = data.get("individual_to_groups", {})
            # Rebuild reverse index
            _group_to_individuals = _build_reverse_index(_individual_to_groups)
            _loaded = True
            log.info(
                "PECOS: loaded %d enrolled NPIs, %d reassignment records from cache",
                len(_enrolled_npis), len(_individual_to_groups),
            )
            return True
    except Exception as e:
        log.warning("PECOS: could not load cache: %s", e)
    return False


def _build_reverse_index(ind_to_grp: dict[str, list[str]]) -> dict[str, list[str]]:
    """Build group_npi -> [individual_npis] from individual -> [group_npis]."""
    rev: dict[str, list[str]] = defaultdict(list)
    for ind_npi, group_npis in ind_to_grp.items():
        for g in group_npis:
            rev[g].append(ind_npi)
    return dict(rev)


# ── Download from CMS ─────────────────────────────────────────────

async def _fetch_paginated(client, url: str, label: str) -> list[dict]:
    """Fetch all pages from a CMS data.cms.gov JSON API endpoint."""
    all_rows: list[dict] = []
    offset = 0
    page = 0
    while page < _MAX_PAGES:
        params = {"size": _PAGE_SIZE, "offset": offset}
        r = await client.get(url, params=params)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or len(rows) == 0:
            break
        all_rows.extend(rows)
        log.info("PECOS %s: fetched page %d (%d rows, %d total)", label, page, len(rows), len(all_rows))
        if len(rows) < _PAGE_SIZE:
            break  # last page
        offset += _PAGE_SIZE
        page += 1
    return all_rows


async def download_pecos_data() -> bool:
    """Download PECOS enrollment + reassignment data from CMS. Non-fatal."""
    global _enrolled_npis, _individual_to_groups, _group_to_individuals, _loaded
    try:
        import httpx

        log.info("PECOS: downloading enrollment data from CMS (this may take a few minutes)...")
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            # ── 1. Enrollment data ──
            enrollment_rows = await _fetch_paginated(client, _ENROLLMENT_URL, "enrollment")
            enrolled = set()
            for row in enrollment_rows:
                npi = str(row.get("NPI") or row.get("npi") or "").strip()
                if npi and len(npi) == 10 and npi.isdigit():
                    enrolled.add(npi)

            log.info("PECOS: parsed %d unique enrolled NPIs from %d enrollment rows",
                     len(enrolled), len(enrollment_rows))

            # ── 2. Reassignment data ──
            reassignment_rows = await _fetch_paginated(client, _REASSIGNMENT_URL, "reassignment")
            ind_to_grp: dict[str, list[str]] = defaultdict(list)
            for row in reassignment_rows:
                # CMS field names vary — try common variants
                ind_npi = str(
                    row.get("INDIVIDUAL_NPI") or row.get("individual_npi")
                    or row.get("REASGN_BNFT_ENRL_NPI") or row.get("reasgn_bnft_enrl_npi")
                    or ""
                ).strip()
                grp_npi = str(
                    row.get("GROUP_PAC_ID_GRP_NPI") or row.get("group_pac_id_grp_npi")
                    or row.get("RCV_BNFT_ENRL_NPI") or row.get("rcv_bnft_enrl_npi")
                    or row.get("GROUP_NPI") or row.get("group_npi")
                    or ""
                ).strip()
                if (ind_npi and len(ind_npi) == 10 and ind_npi.isdigit()
                        and grp_npi and len(grp_npi) == 10 and grp_npi.isdigit()
                        and ind_npi != grp_npi):
                    if grp_npi not in ind_to_grp[ind_npi]:
                        ind_to_grp[ind_npi].append(grp_npi)

            ind_to_grp = dict(ind_to_grp)
            log.info("PECOS: parsed %d individual->group reassignment mappings from %d rows",
                     len(ind_to_grp), len(reassignment_rows))

        # Store in memory
        _enrolled_npis = enrolled
        _individual_to_groups = ind_to_grp
        _group_to_individuals = _build_reverse_index(ind_to_grp)
        _loaded = True

        # Save to local cache
        try:
            cache_data = {
                "enrolled_npis": sorted(_enrolled_npis),
                "individual_to_groups": _individual_to_groups,
            }
            _PECOS_CACHE.write_text(json.dumps(cache_data), encoding="utf-8")
            log.info("PECOS: saved cache to %s", _PECOS_CACHE)
        except Exception as e:
            log.warning("PECOS: could not save cache: %s", e)

        return True
    except Exception as e:
        log.warning("PECOS: download failed (non-fatal): %s", e)
        return False


# ── Public lookup functions ───────────────────────────────────────

def is_medicare_enrolled(npi: str) -> bool:
    """Check if a given NPI appears in the PECOS enrollment data."""
    return npi in _enrolled_npis


def get_reassignment_groups(npi: str) -> list[str]:
    """Get the list of group NPIs this individual reassigns billing to."""
    return _individual_to_groups.get(npi, [])


def get_reassignment_depth(group_npi: str) -> int:
    """Count how many individuals reassign their billing to this group NPI."""
    return len(_group_to_individuals.get(group_npi, []))


def get_reassignment_individuals(group_npi: str) -> list[str]:
    """Get the list of individual NPIs that reassign to this group."""
    return _group_to_individuals.get(group_npi, [])


def get_pecos_stats() -> dict:
    """Summary statistics for the loaded PECOS data."""
    return {
        "loaded": _loaded,
        "enrolled_npi_count": len(_enrolled_npis),
        "individuals_with_reassignments": len(_individual_to_groups),
        "groups_receiving_reassignments": len(_group_to_individuals),
    }
