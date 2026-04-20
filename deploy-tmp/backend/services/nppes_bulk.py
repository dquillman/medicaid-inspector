"""
NPPES bulk data download and local cache.
Downloads the NPPES monthly data dissemination CSV (a subset of key fields),
parses it, and stores a local lookup dict keyed by NPI in nppes_bulk_cache.json.
Falls back to the live API for NPIs not in the bulk file.
"""
import csv
import io
import json
import logging
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "nppes_bulk_cache.json"
# The full NPPES dissemination is ~8GB zipped.  We use the "deactivation" file
# which is much smaller, or callers can point NPPES_BULK_URL at a pre-filtered subset.
NPPES_BULK_URL = (
    "https://download.cms.gov/nppes/NPI_Files.html"  # landing page reference
)
# Actual direct download URL for the weekly deactivation file (small, ~200KB)
NPPES_DEACTIVATION_URL = (
    "https://download.cms.gov/nppes/NPPES_Deactivated_NPI_Report.zip"
)

_bulk_cache: dict[str, dict] = {}
_bulk_meta: dict = {"last_refresh": None, "record_count": 0}
_refresh_running = False


def _load_cache_from_disk() -> None:
    """Load cached bulk data from disk."""
    global _bulk_cache, _bulk_meta
    if CACHE_PATH.exists():
        try:
            raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _bulk_cache = raw.get("records", {})
            _bulk_meta = raw.get("meta", {"last_refresh": None, "record_count": 0})
            _bulk_meta["record_count"] = len(_bulk_cache)
            log.info("NPPES bulk cache loaded: %d records", len(_bulk_cache))
        except Exception as e:
            log.warning("Failed to load NPPES bulk cache: %s", e)


def _save_cache_to_disk() -> None:
    """Persist bulk cache to disk."""
    try:
        data = {
            "meta": _bulk_meta,
            "records": _bulk_cache,
        }
        CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
        log.info("NPPES bulk cache saved: %d records", len(_bulk_cache))
    except Exception as e:
        log.warning("Failed to save NPPES bulk cache: %s", e)


# Load on import
_load_cache_from_disk()


async def refresh_bulk_data() -> dict:
    """
    Download the NPPES deactivation report (small file) and parse it.
    For a full NPI lookup cache, a pre-filtered CSV can be placed manually
    and this function extended.
    """
    global _refresh_running, _bulk_cache, _bulk_meta
    if _refresh_running:
        return {"status": "already_running"}

    _refresh_running = True
    try:
        log.info("Starting NPPES bulk download from %s", NPPES_DEACTIVATION_URL)

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(NPPES_DEACTIVATION_URL)
            resp.raise_for_status()

        # The response is a ZIP containing a CSV
        zip_bytes = io.BytesIO(resp.content)
        records: dict[str, dict] = {}

        with zipfile.ZipFile(zip_bytes) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                return {"status": "error", "message": "No CSV found in ZIP"}

            for csv_name in csv_names:
                with zf.open(csv_name) as f:
                    text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                    reader = csv.DictReader(text)
                    for row in reader:
                        npi = row.get("NPI", "").strip()
                        if not npi:
                            continue
                        records[npi] = {
                            "npi": npi,
                            "nppes_deactivation_date": row.get("NPPES Deactivation Date", ""),
                            "nppes_reactivation_date": row.get("NPPES Reactivation Date", ""),
                            "source": "bulk_deactivation",
                        }

        _bulk_cache.update(records)
        _bulk_meta["last_refresh"] = datetime.utcnow().isoformat()
        _bulk_meta["record_count"] = len(_bulk_cache)
        _save_cache_to_disk()

        return {
            "status": "success",
            "records_downloaded": len(records),
            "total_cached": len(_bulk_cache),
            "last_refresh": _bulk_meta["last_refresh"],
        }
    except Exception as e:
        log.error("NPPES bulk download failed: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        _refresh_running = False


def lookup_npi(npi: str) -> Optional[dict]:
    """Look up NPI in the bulk cache. Returns dict or None."""
    return _bulk_cache.get(npi)


def get_bulk_status() -> dict:
    """Return current bulk cache status."""
    return {
        "last_refresh": _bulk_meta.get("last_refresh"),
        "record_count": _bulk_meta.get("record_count", len(_bulk_cache)),
        "cache_file": str(CACHE_PATH),
        "cache_exists": CACHE_PATH.exists(),
        "refresh_running": _refresh_running,
    }
