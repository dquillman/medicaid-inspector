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
        _REFERRALS_FILE.write_text(
            json.dumps({"referrals": _referrals}, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[referral_workflow] Could not save referrals: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

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
            "case_number": case_number,
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

        now = time.time()

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
