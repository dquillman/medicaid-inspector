"""
Per-se fraud sweep results — read-only lookup over backend/perse_leads.json,
built by scripts/build_perse_sweep.py.

Why this store exists separately from the prescan cache: the prescan only scores
NPIs with $1M+ in lifetime Medicaid payments (106,660 of 617,503 billing NPIs —
94.6% of the dollars). That cutoff is correct for the statistical signals, which
need peer stats to mean anything, and wrong for the per-se ones. An OIG-excluded
provider billing while barred, or a deactivated NPI still collecting, is provable
on the face of it at ANY dollar amount — 42 CFR 1001.1901 has no threshold.

This store holds the sweep of those two checks across the FULL universe, so
leads under the scan cutoff are visible. Measured 2026-07-26: 845 of 1,081 leads
sit outside the scan cache, i.e. MFI could not see them at all before.

Lazy-loaded and GCS-synced, mirroring deactivation_store.
"""
import json
import logging
import pathlib
import threading

log = logging.getLogger(__name__)

_PATH = pathlib.Path(__file__).parent.parent / "perse_leads.json"
_lock = threading.Lock()
_payload: dict = {}
_by_npi: dict[str, dict] = {}
_loaded = False

# Ranked worst-first. active_exclusion is billing DURING an exclusion (per-se
# fraud); recovery_lead is billing that predates it (a clawback, not active
# fraud) and must never be presented as the former.
KINDS = ("active_exclusion", "deactivated_billing", "deactivated_window", "recovery_lead")

KIND_LABELS = {
    "active_exclusion": "Billing while excluded",
    "deactivated_billing": "Billing under a dead NPI",
    "deactivated_window": "Billed while NPI was deactivated",
    "recovery_lead": "Recovery lead (excluded later)",
}


def _load() -> None:
    global _payload, _by_npi, _loaded
    with _lock:
        if _loaded:
            return
        # Reset first. Without this, a reload() after the file goes away (or
        # after a failed parse) kept serving the PREVIOUS sweep — the store
        # would report leads it could no longer justify.
        _payload = {}
        _by_npi = {}
        try:
            if _PATH.exists():
                _payload = json.loads(_PATH.read_text(encoding="utf-8"))
                _by_npi = {r["npi"]: r for r in _payload.get("leads", []) if r.get("npi")}
            _loaded = True
            log.info("[perse] loaded %d per-se leads", len(_by_npi))
        except Exception as e:  # noqa: BLE001
            log.warning("[perse] load failed: %s", e)
            _payload = {}
            _by_npi = {}
            _loaded = True


def reload() -> None:
    """Drop the cache so the next read picks up a freshly built sweep."""
    global _loaded
    with _lock:
        _loaded = False
    _load()


def get_lead(npi: str) -> dict | None:
    """The per-se lead for this NPI, or None. Used to badge a provider page."""
    if not _loaded:
        _load()
    return _by_npi.get(npi)


def list_leads(kind: str | None = None, outside_scan_cache: bool | None = None,
               limit: int = 200, offset: int = 0) -> dict:
    """Filtered slice of the sweep, already ranked worst-first by the builder."""
    if not _loaded:
        _load()
    rows = _payload.get("leads", [])
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if outside_scan_cache is not None:
        rows = [r for r in rows if (r.get("in_scan_cache") is False) == outside_scan_cache]
    total = len(rows)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "leads": rows[offset:offset + limit],
    }


def get_summary() -> dict:
    """Counts + dollars by kind, and how stale the sweep is."""
    if not _loaded:
        _load()
    return {
        "generated_at": _payload.get("generated_at"),
        "scanned_npis": _payload.get("scanned_npis"),
        "total_leads": len(_by_npi),
        "by_kind": _payload.get("summary", {}),
        "available": bool(_by_npi),
    }


def count() -> int:
    if not _loaded:
        _load()
    return len(_by_npi)
