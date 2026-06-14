"""
HHS-OIG Hotline tip log.

Tracks tips the analyst has FILED with the OIG Hotline (the channel the new
/{npi}/oig-tip export feeds), their lifecycle, and outcomes. Distinct from the
MFCU referral workflow (core/referral_workflow.py) — a different agency and
lifecycle. This is the in-app replacement for the manual pitch/tips-log.md and
the evidence source for sales-readiness trigger T1 (an OIG response indicating
action). Persisted to oig_tips.json and synced via GCS.
"""
import pathlib
import threading
import time
import uuid

from core.safe_io import atomic_write_json
import json

_FILE = pathlib.Path(__file__).parent.parent / "oig_tips.json"
_lock = threading.Lock()
_tips: list[dict] = []
_loaded = False

# lifecycle for an OIG Hotline tip
VALID_STATUS = ["filed", "acknowledged", "under_review", "action_taken", "no_action", "closed"]


def _load() -> None:
    global _tips, _loaded
    with _lock:
        if _loaded:
            return
        try:
            if _FILE.exists():
                raw = json.loads(_FILE.read_text(encoding="utf-8"))
                _tips = raw.get("tips", raw) if isinstance(raw, dict) else raw
        except Exception:
            _tips = []
        _loaded = True


def _save() -> None:
    atomic_write_json(_FILE, {"tips": _tips})
    try:
        from core.gcs_sync import upload_file
        upload_file("oig_tips.json")
    except Exception:
        pass


def list_tips() -> list[dict]:
    _load()
    with _lock:
        return sorted(_tips, key=lambda t: t.get("filed_at", 0), reverse=True)


def filed_npis() -> set[str]:
    """NPIs that have an open (not closed/no_action) tip — drives the badge."""
    _load()
    with _lock:
        return {t["npi"] for t in _tips if t.get("npi")}


def get_tip_by_npi(npi: str) -> dict | None:
    _load()
    with _lock:
        for t in _tips:
            if t.get("npi") == npi:
                return dict(t)
    return None


def add_tip(npi: str, provider_name: str = "", state: str = "",
            risk_score: float = 0.0, notes: str = "") -> dict:
    """Idempotent per NPI — returns the existing tip if one is already logged."""
    _load()
    with _lock:
        for t in _tips:
            if t.get("npi") == npi:
                return dict(t)
        now = time.time()
        tip = {
            "id": uuid.uuid4().hex[:12],
            "npi": npi,
            "provider_name": provider_name,
            "state": state,
            "risk_score": round(float(risk_score or 0), 1),
            "status": "filed",
            "reference_number": "",
            "notes": notes,
            "outcome_notes": "",
            "filed_at": now,
            "updated_at": now,
            # OIG never confirms receipt/status; a FOIA "records pertinent to my
            # complaint" request is only appropriate >=6 months after filing.
            "foia_eligible_at": now + 183 * 86400,
            "history": [{"at": now, "status": "filed", "note": "Tip logged as filed with HHS-OIG Hotline"}],
        }
        _tips.append(tip)
    _save()
    return dict(tip)


def update_tip(tip_id: str, status: str | None = None, reference_number: str | None = None,
               notes: str | None = None, outcome_notes: str | None = None) -> dict | None:
    _load()
    with _lock:
        tip = next((t for t in _tips if t.get("id") == tip_id), None)
        if tip is None:
            return None
        now = time.time()
        if status is not None:
            if status not in VALID_STATUS:
                raise ValueError(f"Invalid status {status!r}; must be one of {VALID_STATUS}")
            if status != tip.get("status"):
                tip.setdefault("history", []).append({"at": now, "status": status, "note": ""})
            tip["status"] = status
        if reference_number is not None:
            tip["reference_number"] = reference_number
        if notes is not None:
            tip["notes"] = notes
        if outcome_notes is not None:
            tip["outcome_notes"] = outcome_notes
        tip["updated_at"] = now
        result = dict(tip)
    _save()
    return result


def counts() -> dict:
    _load()
    with _lock:
        by_status = {s: 0 for s in VALID_STATUS}
        for t in _tips:
            by_status[t.get("status", "filed")] = by_status.get(t.get("status", "filed"), 0) + 1
        return {"total": len(_tips), "by_status": by_status}
