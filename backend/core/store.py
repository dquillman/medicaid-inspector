"""
Global mutable state store — avoids circular imports between main.py and routes.
Prescan results are persisted to disk so backend restarts don't re-trigger the scan.
Cache is invalidated by Parquet URL change (new data release) rather than by TTL.
"""
import json
import time
import pathlib

from core.safe_io import atomic_write_json

_CACHE_FILE = pathlib.Path(__file__).parent.parent / "prescan_cache.json"

prescanned_providers: list[dict] = []
_npi_index: dict[str, dict] = {}
prescan_status: dict = {"phase": 0, "message": "Idle — use the Scan button to begin", "started_at": None}
scan_progress: dict = {
    "offset": 0,
    "total_provider_count": None,
    "state_filter": None,
    "batches_completed": 0,
    "last_batch_at": None,
}


# ── disk persistence ──────────────────────────────────────────────────────────

def save_to_disk() -> None:
    from core.config import settings
    try:
        atomic_write_json(_CACHE_FILE, {
            "parquet_url": settings.PARQUET_URL,
            "saved_at": time.time(),
            "scan_progress": scan_progress,
            "providers": prescanned_providers,
        })
    except Exception as e:
        print(f"[store] Could not save cache: {e}")


def load_from_disk() -> bool:
    from core.config import settings
    global prescanned_providers, scan_progress, _npi_index
    try:
        if not _CACHE_FILE.exists():
            return False
        raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        # Invalidate only if a parquet_url is present AND it differs (new data release)
        # If parquet_url is absent it's the old cache format — migrate it
        cached_url = raw.get("parquet_url")
        if cached_url and cached_url != settings.PARQUET_URL:
            print(f"[store] Parquet URL changed — cache invalidated")
            return False
        prescanned_providers = raw.get("providers", [])
        _npi_index = {p["npi"]: p for p in prescanned_providers}
        saved_prog = raw.get("scan_progress", {})
        scan_progress.update({
            "offset": saved_prog.get("offset", 0),
            "total_provider_count": saved_prog.get("total_provider_count"),
            "state_filter": saved_prog.get("state_filter"),
            "batches_completed": saved_prog.get("batches_completed", 0),
            "last_batch_at": saved_prog.get("last_batch_at"),
        })
        print(f"[store] Loaded {len(prescanned_providers)} providers from cache (offset={scan_progress['offset']})")
        return True
    except Exception as e:
        print(f"[store] Could not load cache: {e}")
        return False


# ── in-memory state ───────────────────────────────────────────────────────────

def set_prescanned(data: list[dict]) -> None:
    global prescanned_providers, _npi_index
    prescanned_providers = data
    _npi_index = {p["npi"]: p for p in prescanned_providers}
    save_to_disk()


def append_prescanned(new_providers: list[dict], save: bool = True) -> None:
    """Merge new providers into existing cache, de-dup by NPI, sort by total_paid DESC."""
    global prescanned_providers, _npi_index
    for p in new_providers:
        _npi_index[p["npi"]] = p
    prescanned_providers = sorted(_npi_index.values(), key=lambda p: p.get("total_paid") or 0, reverse=True)
    if save:
        save_to_disk()


def get_prescanned() -> list[dict]:
    return prescanned_providers


def get_provider_by_npi(npi: str) -> dict | None:
    """O(1) lookup of a single provider by NPI."""
    return _npi_index.get(npi)


def load_prescanned_from_disk() -> bool:
    """Call once at startup. Returns True if cache was loaded successfully."""
    return load_from_disk()


def get_scan_progress() -> dict:
    return dict(scan_progress)


def set_scan_progress(offset: int, total: int | None, state_filter: str | None, batches: int, save: bool = True) -> None:
    global scan_progress
    scan_progress = {
        "offset": offset,
        "total_provider_count": total,
        "state_filter": state_filter,
        "batches_completed": batches,
        "last_batch_at": time.time(),
    }
    if save:
        save_to_disk()


def reset_scan() -> None:
    """Clear all scanned providers and reset progress to zero."""
    global prescanned_providers, scan_progress, _npi_index
    prescanned_providers = []
    _npi_index = {}
    scan_progress = {
        "offset": 0,
        "total_provider_count": None,
        "state_filter": None,
        "batches_completed": 0,
        "last_batch_at": None,
    }
    try:
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
    except Exception as e:
        print(f"[store] Could not delete cache file: {e}")


def set_prescan_status(phase: int, message: str) -> None:
    global prescan_status
    started_at = prescan_status.get("started_at")
    # Start timer when a new scan begins (transition from idle to active)
    if phase > 0 and (started_at is None or prescan_status.get("phase", 0) == 0):
        started_at = time.time()
    elif phase == 0:
        started_at = None
    prescan_status = {
        "phase": phase,
        "message": message,
        "started_at": started_at,
    }


def get_prescan_status() -> dict:
    s = dict(prescan_status)
    if s.get("started_at"):
        s["elapsed_sec"] = round(time.time() - s["started_at"])
    else:
        s["elapsed_sec"] = 0
    s["scan_progress"] = get_scan_progress()
    return s
