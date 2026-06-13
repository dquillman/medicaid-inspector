"""
Deactivated-NPI lookup. A provider still billing Medicaid under an NPI that CMS
has DEACTIVATED is a per-se unauthorized-billing / identity-theft lead — the
highest-credibility, payer-agnostic indicator in the toolkit.

Loads backend/npi_deactivations.json ({npi: deactivation_date}) built by
scripts/build_deactivations.py from the NPPES bulk file. Synced via GCS and
lazy-loaded on first use, mirroring oig_store.
"""
import json
import logging
import pathlib
import threading

log = logging.getLogger(__name__)

_PATH = pathlib.Path(__file__).parent.parent / "npi_deactivations.json"
_lock = threading.Lock()
_deacts: dict[str, str] = {}
_loaded = False


def _load() -> None:
    global _deacts, _loaded
    with _lock:
        if _loaded:
            return
        try:
            if _PATH.exists():
                _deacts = json.loads(_PATH.read_text(encoding="utf-8"))
            _loaded = True
            log.info("[deactivation] loaded %d deactivated NPIs", len(_deacts))
        except Exception as e:  # noqa: BLE001
            log.warning("[deactivation] load failed: %s", e)
            _loaded = True


def get_deactivation(npi: str) -> str | None:
    """Deactivation date string for the NPI, or None if active/unknown."""
    if not _loaded:
        _load()
    return _deacts.get(npi)


def is_deactivated(npi: str) -> bool:
    return get_deactivation(npi) is not None


def count() -> int:
    if not _loaded:
        _load()
    return len(_deacts)
