"""
Loader for precomputed analysis results.

Cloud Run runs on the slim prescan cache (no per-HCPCS detail) and cannot
afford the full 1.4 GB cache in its 2 GiB container, so the heavy claim-level
analyses (claim patterns, pharmacy, DME, doctor shopping) are precomputed on
a workstation that has the full cache — see scripts/precompute_analyses.py —
and shipped as a small JSON synced through GCS like the other state files.

Services call get_precomputed(section) on their slim-cache path before
falling back to the "requires full cache" note.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

log = logging.getLogger(__name__)

_PATH = pathlib.Path(__file__).parent.parent / "precomputed_analyses.json"
_state: dict[str, Any] = {"data": None, "mtime": 0.0}


def get_precomputed(section: str) -> Any | None:
    """Return one section of the precomputed analyses, or None if unavailable.

    Reloads from disk when the file's mtime changes (the GCS startup sync can
    refresh it under a warm instance).
    """
    try:
        if not _PATH.exists():
            return None
        mtime = _PATH.stat().st_mtime
        if _state["data"] is None or mtime != _state["mtime"]:
            with open(_PATH, encoding="utf-8") as f:
                _state["data"] = json.load(f)
            _state["mtime"] = mtime
            log.info(
                "[precomputed] Loaded %s (generated_at=%s, spec_version=%s)",
                _PATH.name, (_state["data"] or {}).get("generated_at", "?"),
                (_state["data"] or {}).get("spec_version", "?"),
            )
            _warn_if_stale(_state["data"] or {})
        data = _state["data"] or {}
        return data.get(section)
    except Exception as e:
        log.warning("[precomputed] Failed to load %s: %s", _PATH.name, e)
        return None


def _warn_if_stale(data: dict) -> None:
    """Visibly flag a precomputed file produced by older detection logic
    (audit 2026-10-24, item 9) — a silent reload would keep serving
    unbundling/pos/modifiers results scored by a since-changed spec without
    anyone knowing. Logs only; a UI staleness banner is a reasonable
    follow-up this doesn't attempt."""
    from services.claim_patterns import SPEC_VERSION as current_version
    file_version = data.get("spec_version")
    if file_version != current_version:
        log.warning(
            "[precomputed] %s was generated with claim_patterns spec_version=%r, "
            "current code expects %r — claim-pattern leads (unbundling/pos/modifiers/"
            "impossible) may reflect stale detection logic until the next "
            "precompute run.", _PATH.name, file_version, current_version,
        )


def get_generated_at() -> str | None:
    """Timestamp string of the current precomputed file, if loaded."""
    if get_precomputed("generated_at") is not None:
        return _state["data"].get("generated_at")
    return None


def get_staleness_info() -> dict:
    """Explicit {is_stale, file_version, current_version} for callers that
    want to surface this rather than only grep the logs."""
    from services.claim_patterns import SPEC_VERSION as current_version
    get_precomputed("generated_at")  # ensure loaded
    data = _state["data"] or {}
    file_version = data.get("spec_version")
    return {
        "is_stale": file_version != current_version,
        "file_version": file_version,
        "current_version": current_version,
    }
