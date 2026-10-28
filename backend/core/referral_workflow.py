"""
MFCU Referral Workflow.
Tracks referrals to Medicaid Fraud Control Units (MFCUs) through their lifecycle.
Persisted to backend/referrals.json.
"""
import json
import time
import pathlib
import threading
import uuid
from typing import Optional

from core.safe_io import atomic_write_json

_REFERRALS_FILE = pathlib.Path(__file__).parent.parent / "referrals.json"

_referrals: list[dict] = []
_next_id: int = 1
_lock = threading.Lock()

REFERRAL_STAGES = [
    "draft",
    "submitted",
    "acknowledged",
    "under_investigation",
    "outcome_received",
]

VALID_OUTCOMES = [
    "substantiated",
    "unsubstantiated",
    "settlement",
    "criminal_charges",
    "civil_action",
    "declined",
    "pending",
]

# The only INDEPENDENTLY SUBSTANTIATED outcomes — an agency outside this app
# actually investigated and agreed. Everything else (filing the referral,
# "pending", the analyst's own "confirmed" assessment) is weaker evidence and
# must not be presented as a verified fraud label (audit 2026-10-24, item 3).
SUBSTANTIATED_OUTCOMES = {"substantiated"}
# An agency reviewed the case and found it did NOT hold up — genuine negative
# signal, stronger than an internal "dismissed".
REJECTED_OUTCOMES = {"unsubstantiated"}


# ── disk persistence ──────────────────────────────────────────────────────────

def load_referrals_from_disk() -> None:
    global _referrals, _next_id
    try:
        if not _REFERRALS_FILE.exists():
            return
        raw = json.loads(_REFERRALS_FILE.read_text(encoding="utf-8"))
        _referrals = raw.get("referrals", [])
        if _referrals:
            _next_id = max(r.get("id", 0) for r in _referrals) + 1
        print(f"[referral_workflow] Loaded {len(_referrals)} referrals from disk")
    except Exception as e:
        print(f"[referral_workflow] Could not load referrals: {e}")


def _save_to_disk() -> None:
    try:
        # Was a raw write_text — a crash mid-write truncated referrals.json
        # (audit 2026-10-24, item 10). atomic_write_json writes to a temp file
        # and os.replace()s it, so a crash leaves the original file intact.
        atomic_write_json(_REFERRALS_FILE, {"referrals": _referrals})
        # Sync to GCS — the container's local disk is ephemeral on Cloud Run,
        # so without this every submit/update/delete is lost on restart.
        try:
            from core.gcs_sync import upload_file
            upload_file("referrals.json")
        except Exception:
            pass  # GCS unavailable locally — the local write is still done
    except Exception as e:
        print(f"[referral_workflow] Could not save referrals: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

def make_case_number(npi: str, when: float | None = None, channel: str = "MFCU") -> str:
    """Mint the case number MFI assigns itself.

    Neither HHS-OIG nor the state MFCUs hand back a tracking number (OIG
    explicitly does not confirm receipt), so waiting for an external ID means
    the field stays empty forever and there is nothing to quote in a follow-up.
    MFI issues its own: MFI-<CHANNEL>-<NPI>-<YYYYMMDD>. Deterministic, unique
    per provider per channel per day, and readable aloud on a phone call. If an
    agency ever DOES supply a real number, it overwrites this.
    """
    import datetime
    ts = datetime.datetime.fromtimestamp(when or time.time())
    return f"MFI-{channel.upper()}-{npi}-{ts.strftime('%Y%m%d')}"


def create_referral(
    npi: str,
    submitted_by: str,
    mfcu_contact: str = "",
    jurisdiction: str = "",
    case_number: str = "",
    notes: str = "",
) -> dict:
    """Create a new MFCU referral for a provider."""
    global _next_id
    now = time.time()

    with _lock:
        referral = {
            "id": _next_id,
            "referral_id": f"REF-{_next_id:05d}",
            "npi": npi,
            "stage": "submitted",
            "mfcu_contact": mfcu_contact,
            "jurisdiction": jurisdiction,
            # App-assigned when the agency gives us nothing (the normal case).
            "case_number": case_number or make_case_number(npi, now, "MFCU"),
            "referral_date": now,
            "submitted_by": submitted_by,
            "outcome": None,
            "outcome_date": None,
            "outcome_notes": "",
            "notes": notes,
            "created_at": now,
            "updated_at": now,
            "history": [
                {
                    "stage": "submitted",
                    "timestamp": now,
                    "by": submitted_by,
                    "note": "Referral submitted to MFCU",
                }
            ],
        }
        _referrals.append(referral)
        _next_id += 1
        _save_to_disk()

    return referral


def update_referral(
    referral_id: int,
    stage: Optional[str] = None,
    outcome: Optional[str] = None,
    outcome_notes: Optional[str] = None,
    mfcu_contact: Optional[str] = None,
    case_number: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    notes: Optional[str] = None,
    updated_by: str = "system",
    evidence_reference: Optional[str] = None,
) -> Optional[dict]:
    """Update a referral's stage, outcome, or metadata."""
    with _lock:
        ref = None
        for r in _referrals:
            if r["id"] == referral_id:
                ref = r
                break
        if ref is None:
            return None

        effective_reference = (evidence_reference if evidence_reference is not None else ref.get("evidence_reference", "")).strip()
        if outcome in SUBSTANTIATED_OUTCOMES | REJECTED_OUTCOMES and not effective_reference:
            raise ValueError("Documented outcome requires an evidence reference (agency document, URL, or case record)")
        now = time.time()
        if evidence_reference is not None:
            ref["evidence_reference"] = effective_reference

        if stage is not None:
            if stage not in REFERRAL_STAGES:
                raise ValueError(f"Invalid stage: {stage!r}. Must be one of {REFERRAL_STAGES}")
            old_stage = ref["stage"]
            ref["stage"] = stage
            ref["history"].append({
                "stage": stage,
                "timestamp": now,
                "by": updated_by,
                "note": f"Stage changed from {old_stage} to {stage}",
            })

        if outcome is not None:
            if outcome not in VALID_OUTCOMES:
                raise ValueError(f"Invalid outcome: {outcome!r}. Must be one of {VALID_OUTCOMES}")
            ref["outcome"] = outcome
            ref["outcome_date"] = now
            ref["stage"] = "outcome_received"
            ref["history"].append({
                "stage": "outcome_received",
                "timestamp": now,
                "by": updated_by,
                "note": f"Outcome received: {outcome}",
            })
            # This is the one place a referral's outcome is INDEPENDENTLY
            # substantiated or rejected by an outside agency — feed it to the
            # feedback loop as real ground truth. Best-effort: an outcome
            # update must never fail because feedback recording failed.
            try:
                _refresh_outcome_feedback(ref["npi"])
            except Exception:
                import logging as _l
                _l.getLogger(__name__).warning(
                    "feedback recording failed for referral outcome on %s", ref.get("npi"), exc_info=True)

        if outcome_notes is not None:
            ref["outcome_notes"] = outcome_notes
        if mfcu_contact is not None:
            ref["mfcu_contact"] = mfcu_contact
        if case_number is not None:
            ref["case_number"] = case_number
        if jurisdiction is not None:
            ref["jurisdiction"] = jurisdiction
        if notes is not None:
            ref["notes"] = notes

        ref["updated_at"] = now
        _save_to_disk()

    return ref


def delete_referral(referral_id: int) -> Optional[dict]:
    """Remove a referral record (e.g. a mistaken or test entry). Returns the
    deleted record, or None if not found. Referrals are normally append-only
    history, so this is an admin-only correction path."""
    with _lock:
        for i, r in enumerate(_referrals):
            if r["id"] == referral_id:
                removed = _referrals.pop(i)
                _save_to_disk()
                _refresh_outcome_feedback(removed["npi"])
                return removed
    return None


def npi_has_active_referral(npi: str) -> bool:
    """True if the provider has a referral in an active stage (submitted /
    acknowledged / under_investigation). Used to keep the MFCU referral flow
    and the case ledger consistent."""
    active = {"submitted", "acknowledged", "under_investigation"}
    with _lock:
        return any(r["npi"] == npi and r.get("stage") in active for r in _referrals)


# ── queries ───────────────────────────────────────────────────────────────────

def get_referrals(
    stage_filter: Optional[str] = None,
    npi_filter: Optional[str] = None,
) -> list[dict]:
    """Return referrals, optionally filtered by stage or NPI."""
    items = list(_referrals)
    if stage_filter:
        items = [r for r in items if r["stage"] == stage_filter]
    if npi_filter:
        items = [r for r in items if r["npi"] == npi_filter]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


def get_referral_by_id(referral_id: int) -> Optional[dict]:
    """Return a single referral by ID."""
    for r in _referrals:
        if r["id"] == referral_id:
            return r
    return None


def get_referral_by_npi(npi: str) -> list[dict]:
    """Return all referrals for a given NPI."""
    items = [r for r in _referrals if r["npi"] == npi]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


def get_referral_stats() -> dict:
    """Return aggregate referral statistics."""
    from collections import Counter
    by_stage = Counter(r["stage"] for r in _referrals)
    by_outcome = Counter(r["outcome"] for r in _referrals if r["outcome"])
    unique_npis = len(set(r["npi"] for r in _referrals))

    return {
        "total_referrals": len(_referrals),
        "unique_providers": unique_npis,
        "by_stage": dict(by_stage),
        "by_outcome": dict(by_outcome),
    }


def get_verified_labels() -> dict[str, int]:
    """Documented independent findings only; contradictory findings stay unknown.

    Charges, settlements, declining a referral, and analyst dispositions are
    not adjudications of the underlying allegation. Legacy rows without a
    source reference remain intact but do not enter validation or training.
    """
    candidates: dict[str, set[int]] = {}
    for ref in get_referrals():
        if not str(ref.get("evidence_reference") or "").strip():
            continue
        outcome = ref.get("outcome")
        label = 1 if outcome in SUBSTANTIATED_OUTCOMES else 0 if outcome in REJECTED_OUTCOMES else None
        if ref.get("npi") and label is not None:
            candidates.setdefault(ref["npi"], set()).add(label)
    return {npi: next(iter(labels)) for npi, labels in candidates.items() if len(labels) == 1}


def _refresh_outcome_feedback(npi: str) -> None:
    """Reconcile feedback against all remaining documented referral findings."""
    from services.feedback_tracker import record_confirmation, record_dismissal, clear_label
    label = get_verified_labels().get(npi)
    if label is None:
        clear_label(npi, source="independent_outcome")
    else:
        accepted = SUBSTANTIATED_OUTCOMES if label == 1 else REJECTED_OUTCOMES
        reference = next(str(row["evidence_reference"]) for row in get_referrals()
                         if row.get("npi") == npi and row.get("outcome") in accepted
                         and str(row.get("evidence_reference") or "").strip())
        record = record_confirmation if label == 1 else record_dismissal
        record(npi, source="independent_outcome", evidence_reference=reference)
    from services.supervised_scorer import schedule_retrain
    schedule_retrain()
