"""
Global mutable state store — avoids circular imports between main.py and routes.
Prescan results are persisted to disk so backend restarts don't re-trigger the scan.
Cache is invalidated by dataset filename OR content-size change (a new/restated
data release) rather than by TTL — so per-provider aggregates can't go stale
against the fully-rebuilt network/hcpcs indexes.
"""
import json
import time
import pathlib
import threading

from core.safe_io import atomic_write_json

_CACHE_FILE = pathlib.Path(__file__).parent.parent / "prescan_cache.json"

_store_lock = threading.Lock()
prescanned_providers: list[dict] = []
_npi_index: dict[str, dict] = {}
_last_loaded_at: float | None = None
_last_loaded_filename: str | None = None
prescan_status: dict = {"phase": 0, "message": "Idle — use the Scan button to begin", "started_at": None}
scan_progress: dict = {
    "offset": 0,
    "total_provider_count": None,
    "state_filter": None,
    "batches_completed": 0,
    "last_batch_at": None,
}


# ── disk persistence ──────────────────────────────────────────────────────────

def _dataset_fingerprint() -> str:
    """Content signature of the dataset the app actually reads.

    The filename-only invalidation below misses a dataset that is updated IN
    PLACE (same filename, new/restated rows) — which let stale per-provider
    aggregates survive while the fully-rebuilt network/hcpcs indexes moved on,
    the source of the detail-vs-network claim-count drift. The file SIZE changes
    whenever the content changes, and is stable across identical re-downloads, so
    it invalidates on a real data refresh without needlessly discarding 100k+
    providers of scan state. Falls back to the filename when the parquet isn't
    local (can't cheaply size a remote object) — the caller only acts when both
    sides carry a real size signature."""
    from core.config import settings
    url = settings.PARQUET_URL or ""
    name = url.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    try:
        from data.duckdb_client import get_parquet_path
        p = pathlib.Path(get_parquet_path())
        if p.exists() and p.is_file():
            return f"{name}:{p.stat().st_size}"
    except Exception:
        pass
    return name


def save_to_disk() -> None:
    from core.config import settings
    try:
        atomic_write_json(_CACHE_FILE, {
            "parquet_url": settings.PARQUET_URL,
            "dataset_fingerprint": _dataset_fingerprint(),
            "saved_at": time.time(),
            "scan_progress": scan_progress,
            "providers": prescanned_providers,
        })
    except Exception as e:
        print(f"[store] Could not save cache: {e}")


def load_from_disk(filename: str = "prescan_cache.json") -> bool:
    from core.config import settings
    global prescanned_providers, scan_progress, _npi_index, _last_loaded_at, _last_loaded_filename
    try:
        cache_file = pathlib.Path(__file__).parent.parent / filename
        if not cache_file.exists():
            return False
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        # Cache invalidation policy: only invalidate when the dataset _filename_
        # changes (signaling a new data release). Different hosts (Azure vs GCS
        # vs local file path) serving the same underlying dataset shouldn't
        # discard 100k+ providers of scan state.
        cached_url = raw.get("parquet_url") or ""
        current_url = settings.PARQUET_URL or ""
        def _dataset_key(url: str) -> str:
            # Last path segment after the final '/', minus query string
            tail = url.rsplit("/", 1)[-1].split("?", 1)[0].lower()
            return tail
        if cached_url and _dataset_key(cached_url) != _dataset_key(current_url):
            print(f"[store] Dataset filename changed ({_dataset_key(cached_url)} -> {_dataset_key(current_url)}) — cache invalidated")
            return False
        if cached_url and cached_url != current_url:
            print(f"[store] Parquet host changed but dataset filename matches — keeping cache")
        # Content check: same filename but a different file SIZE means the dataset
        # was updated in place (new/restated rows). Invalidate so the scan rebuilds
        # every provider instead of retaining stale aggregates (detail-vs-network
        # drift). Only acts when BOTH sides carry a real size signature, so a
        # not-yet-downloaded remote dataset never discards a good cache.
        cached_fp = raw.get("dataset_fingerprint") or ""
        current_fp = _dataset_fingerprint()
        if ":" in cached_fp and ":" in current_fp and cached_fp != current_fp:
            print(f"[store] Dataset content changed ({cached_fp} -> {current_fp}) — cache invalidated for a fresh re-scan")
            return False
        loaded_providers = raw.get("providers", [])
        loaded_index = {p["npi"]: p for p in loaded_providers}
        saved_prog = raw.get("scan_progress", {})
        with _store_lock:
            prescanned_providers = loaded_providers
            _npi_index = loaded_index
            _last_loaded_at = time.time()
            _last_loaded_filename = filename
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
    with _store_lock:
        prescanned_providers = data
        _npi_index = {p["npi"]: p for p in prescanned_providers}
    save_to_disk()


def append_prescanned(new_providers: list[dict], save: bool = True) -> None:
    """Merge new providers into existing cache, de-dup by NPI, sort by total_paid DESC."""
    global prescanned_providers, _npi_index
    with _store_lock:
        for p in new_providers:
            _npi_index[p["npi"]] = p
        prescanned_providers = sorted(_npi_index.values(), key=lambda p: p.get("total_paid") or 0, reverse=True)
    if save:
        save_to_disk()


def get_prescanned() -> list[dict]:
    with _store_lock:
        return list(prescanned_providers)


def get_provider_by_npi(npi: str) -> dict | None:
    """O(1) lookup of a single provider by NPI."""
    with _store_lock:
        return _npi_index.get(npi)


def get_prescanned_snapshot() -> list[dict]:
    """Return the live provider list WITHOUT copying — treat as read-only.

    Updates always rebind the module global (set/append/reset/load all assign a
    new list, never mutate in place), so the returned object is a stable
    snapshot and its identity is a valid cache key for derived lookups.
    """
    return prescanned_providers


def load_prescanned_from_disk(filename: str = "prescan_cache.json") -> bool:
    """Call once at startup. Returns True if cache was loaded successfully."""
    return load_from_disk(filename)


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
    with _store_lock:
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


def get_cache_status() -> dict:
    """Snapshot of slim/full prescan cache state for diagnostics."""
    slim_path = pathlib.Path(__file__).parent.parent / "prescan_slim.json"
    full_path = pathlib.Path(__file__).parent.parent / "prescan_cache.json"

    def _file_info(p: pathlib.Path) -> dict:
        if not p.exists():
            return {"exists": False, "size_mb": 0.0, "mtime": None}
        st = p.stat()
        return {"exists": True, "size_mb": round(st.st_size / (1024 * 1024), 2), "mtime": st.st_mtime}

    with _store_lock:
        provider_count = len(prescanned_providers)
        loaded_at = _last_loaded_at
        loaded_from = _last_loaded_filename
    return {
        "loaded_providers": provider_count,
        "loaded_at": loaded_at,
        "loaded_from": loaded_from,
        "slim_file": _file_info(slim_path),
        "full_file": _file_info(full_path),
        "cloud_run": bool(__import__("os").environ.get("K_SERVICE")),
    }


def get_prescan_status() -> dict:
    s = dict(prescan_status)
    if s.get("started_at"):
        s["elapsed_sec"] = round(time.time() - s["started_at"])
    else:
        s["elapsed_sec"] = 0
    s["scan_progress"] = get_scan_progress()
    return s
