"""
OIG LEIE (List of Excluded Individuals/Entities) — fast NPI lookup.

At startup: tries to load from local cache (oig_exclusions.json).
If no cache, attempts to download the public CSV from HHS.
All failures are non-fatal — the app works fine without this data.
"""
import csv
import io
import json
import pathlib
import logging

log = logging.getLogger(__name__)

_OIG_CACHE   = pathlib.Path(__file__).parent.parent / "oig_exclusions.json"
_OIG_CSV_URL = "https://oig.hhs.gov/exclusions/downloads/UPDATED.csv"

# In-memory: NPI (10-digit string) -> exclusion record dict
_exclusions: dict[str, dict] = {}
_loaded = False


def load_oig_from_disk() -> bool:
    """Try to load the cached exclusion list. Returns True if successful."""
    global _exclusions, _loaded
    try:
        if _OIG_CACHE.exists():
            data = json.loads(_OIG_CACHE.read_text(encoding="utf-8"))
            _exclusions = data
            _loaded = True
            log.info("OIG: loaded %d NPI-linked exclusion records from cache", len(_exclusions))
            return True
    except Exception as e:
        log.warning("OIG: could not load cache: %s", e)
    return False


async def download_oig_list() -> bool:
    """Download the OIG LEIE CSV from HHS and cache it by NPI. Non-fatal."""
    global _exclusions, _loaded
    try:
        import httpx
        log.info("OIG: downloading LEIE from HHS…")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(_OIG_CSV_URL)
            r.raise_for_status()
            text = r.text

        records: dict[str, dict] = {}
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            npi = (row.get("NPI") or "").strip()
            if npi and len(npi) == 10 and npi.isdigit():
                # Build name from individual or business name
                fname = (row.get("FIRSTNAME") or "").strip()
                lname = (row.get("LASTNAME") or "").strip()
                bname = (row.get("BUSNAME") or "").strip()
                name  = f"{fname} {lname}".strip() if fname or lname else bname
                records[npi] = {
                    "npi":       npi,
                    "name":      name,
                    "busname":   bname,
                    "specialty": (row.get("SPECIALTY") or "").strip(),
                    "excl_type": (row.get("EXCL_TYPE") or "").strip(),
                    "excl_date": (row.get("EXCL_DATE") or "").strip(),
                    "state":     (row.get("STATE") or "").strip(),
                }

        _exclusions = records
        _loaded = True

        # Save to local cache so next startup doesn't need to download
        try:
            _OIG_CACHE.write_text(json.dumps(_exclusions), encoding="utf-8")
        except Exception as e:
            log.warning("OIG: could not save cache: %s", e)

        log.info("OIG: downloaded %d NPI-linked exclusion records", len(records))
        return True
    except Exception as e:
        log.warning("OIG: download failed (non-fatal): %s", e)
        return False


def is_excluded(npi: str) -> tuple[bool, dict | None]:
    """Check if a given NPI is on the OIG exclusion list."""
    record = _exclusions.get(npi)
    return record is not None, record


def get_oig_stats() -> dict:
    return {"loaded": _loaded, "record_count": len(_exclusions)}
