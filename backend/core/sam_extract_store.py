"""
SAM.gov exclusions via the PUBLIC daily extract — no API key required.

GSA publishes the complete active-exclusions list daily as a keyless download:
  https://sam.gov/api/prod/fileextractservices/v1/api/download/
      Exclusions/Public%20V2/SAM_Exclusions_Public_Extract_V2_{yy}{doy}.ZIP

This store downloads the newest extract (walking back a few days for publish
lag), parses it fully in memory (~12 MB zip / ~110k records), and answers
NPI-first lookups with a name fallback. It is the default SAM source when no
SAM_API_KEY is configured; the live API (core/sam_store.py) remains preferred
when a key exists, since it is intraday-fresh.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_URL = ("https://sam.gov/api/prod/fileextractservices/v1/api/download/"
        "Exclusions/Public%20V2/SAM_Exclusions_Public_Extract_V2_{stamp}.ZIP")
_REFRESH_AFTER = timedelta(days=3)
_LOOKBACK_DAYS = 7

_lock = asyncio.Lock()
_by_npi: dict[str, list[dict]] = {}
_by_name: dict[str, list[dict]] = {}
_as_of: str = ""                       # publish date of the loaded file (data vintage)
_loaded_at: datetime | None = None     # UTC of the last SUCCESSFUL download+parse
_last_attempt: datetime | None = None  # UTC of the last refresh attempt (ok or not)
_last_error: str = ""                  # message from the last failed attempt
_record_count = 0


def status() -> dict:
    """Freshness of the SAM public-extract source — so MFI/HAL can state exactly
    when it last updated successfully, not just what the data vintage is."""
    ok = _loaded_at is not None and _record_count > 0
    next_due = (_loaded_at + _REFRESH_AFTER).isoformat() + "Z" if _loaded_at else None
    return {
        "source": "SAM.gov public exclusions extract",
        "loaded": ok,
        "last_success_utc": _loaded_at.isoformat() + "Z" if _loaded_at else None,
        "data_as_of": _as_of or None,          # the extract's own publish date
        "record_count": _record_count,
        "refresh_interval_days": _REFRESH_AFTER.days,
        "next_refresh_due_utc": next_due,
        "last_attempt_utc": _last_attempt.isoformat() + "Z" if _last_attempt else None,
        "last_error": _last_error or None,
    }


def _slim(row: dict) -> dict:
    name = (row.get("Name") or "").strip() or " ".join(
        p for p in (row.get("First", ""), row.get("Middle", ""), row.get("Last", ""))
        if p).strip()
    return {
        "classification": row.get("Classification", ""),
        "name": name,
        "exclusion_program": row.get("Exclusion Program", ""),
        "excluding_agency": row.get("Excluding Agency", ""),
        "exclusion_type": row.get("Exclusion Type", ""),
        "active_date": row.get("Active Date", ""),
        "termination_date": row.get("Termination Date", ""),
        "sam_number": row.get("SAM Number", ""),
        "npi": (row.get("NPI") or "").strip(),
        "state": row.get("State / Province", ""),
    }


async def _download() -> tuple[bytes, str] | None:
    import httpx
    now = datetime.utcnow()
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        for back in range(_LOOKBACK_DAYS):
            d = now - timedelta(days=back)
            stamp = f"{d:%y}{d.timetuple().tm_yday:03d}"
            url = _URL.format(stamp=stamp)
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 100_000:
                    return resp.content, f"{d:%Y-%m-%d}"
            except Exception as e:  # noqa: BLE001 — try the previous day
                log.info("SAM extract fetch %s failed: %s", stamp, e)
    return None


async def ensure_loaded() -> bool:
    """Load (or refresh) the extract. Returns True when data is available."""
    global _by_npi, _by_name, _as_of, _loaded_at, _last_attempt, _last_error, _record_count
    async with _lock:
        if _loaded_at and datetime.utcnow() - _loaded_at < _REFRESH_AFTER:
            return _record_count > 0
        _last_attempt = datetime.utcnow()
        got = await _download()
        if not got:
            _last_error = "download failed (GSA extract unreachable for all lookback days)"
            log.warning("SAM public extract unavailable (kept %d cached records)",
                        _record_count)
            return _record_count > 0
        blob, as_of = got
        by_npi: dict[str, list[dict]] = {}
        by_name: dict[str, list[dict]] = {}
        count = 0
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            with z.open(z.namelist()[0]) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8",
                                                         errors="replace"))
                for row in reader:
                    rec = _slim(row)
                    count += 1
                    # index only plausible NPIs: 10 digits, first digit 1 or 2
                    # (the extract contains placeholder junk like 0000000000)
                    n = rec["npi"]
                    if n and len(n) == 10 and n.isdigit() and n[0] in "12":
                        by_npi.setdefault(n, []).append(rec)
                    if rec["name"]:
                        by_name.setdefault(rec["name"].upper(), []).append(rec)
        _by_npi, _by_name = by_npi, by_name
        _as_of, _loaded_at, _record_count = as_of, datetime.utcnow(), count
        _last_error = ""
        log.info("SAM public extract loaded: %d records (%d with NPI), as of %s",
                 count, len(by_npi), as_of)
        return count > 0


async def check_extract(npi: str = "", name: str = "") -> dict:
    """Check the public extract. Same shape as sam_store.check_sam_exclusion."""
    ok = await ensure_loaded()
    if not ok:
        return {"error": ("SAM public extract could not be downloaded and no "
                          "cached copy exists — SAM check unavailable.")}
    hits: list[dict] = []
    matched_by = ""
    if npi and npi in _by_npi:
        hits = _by_npi[npi]
        matched_by = "npi"
    elif name and name.strip().upper() in _by_name:
        hits = _by_name[name.strip().upper()]
        matched_by = "name (exact match only — verify identity)"
    return {
        "excluded": bool(hits),
        "records": hits[:5],
        "matched_by": matched_by,
        "source": "SAM.gov public exclusions extract",
        "as_of": _as_of,
        "last_success_utc": _loaded_at.isoformat() + "Z" if _loaded_at else None,
        "records_in_list": _record_count,
    }
