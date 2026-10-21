"""
Medicare revocation lookup — backend/medicare_revocations.json, built by
scripts/build_revocations.py from the CMS Revocation Extract.

A Medicare-revoked provider must be terminated by state Medicaid
(42 CFR 455.416(c)), so Medicaid billing after the revocation date is a per-se
lead. The per-se sweep does the billing comparison offline; this store only
answers "is this NPI revoked, and when". Small (~7k NPIs). Lazy-loaded and
GCS-synced, mirroring deactivation_store.
"""
import json
import logging
import pathlib
import threading

log = logging.getLogger(__name__)

_PATH = pathlib.Path(__file__).parent.parent / "medicare_revocations.json"
_lock = threading.Lock()
_revs: dict[str, list[dict]] = {}
_generated_at: str | None = None
_loaded = False


def _load() -> None:
    global _revs, _generated_at, _loaded
    with _lock:
        if _loaded:
            return
        _revs, _generated_at = {}, None
        try:
            if _PATH.exists():
                payload = json.loads(_PATH.read_text(encoding="utf-8"))
                _revs = payload.get("revocations") or {}
                _generated_at = payload.get("generated_at")
            log.info("[revocation] loaded %d Medicare-revoked NPIs", len(_revs))
        except Exception as e:  # noqa: BLE001
            log.warning("[revocation] load failed: %s", e)
            _revs = {}
        _loaded = True


def reload() -> None:
    global _loaded
    with _lock:
        _loaded = False
    _load()


def get_revocations(npi: str) -> list[dict]:
    """Every revoked Medicare enrollment for this NPI, oldest first ([] if none)."""
    if not _loaded:
        _load()
    return _revs.get(npi) or []


def is_revoked(npi: str) -> bool:
    return bool(get_revocations(npi))


def all_revocations() -> dict[str, list[dict]]:
    if not _loaded:
        _load()
    return _revs


def count() -> int:
    if not _loaded:
        _load()
    return len(_revs)


def generated_at() -> str | None:
    if not _loaded:
        _load()
    return _generated_at
