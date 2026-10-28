"""
False Positive Feedback Tracker.

Tracks dismissed (false positive) cases and uses them to adjust signal
weight confidence over time. When a provider is dismissed, the signals
that were active at dismissal are recorded as false positives.

Over time, signals with high false positive rates get their effective
weight dampened, improving the composite score accuracy.
"""
import json
import logging
import pathlib
import time
from typing import Optional

from core.safe_io import atomic_write_json

log = logging.getLogger(__name__)

_FEEDBACK_FILE = pathlib.Path(__file__).parent.parent / "feedback_data.json"

# Synthetic/test fixture NPIs that must never contribute to real feedback
# counts. "1234567890" is conftest.py's SAMPLE_PROVIDERS "Test Provider A" —
# it leaked into production feedback_data.json (confirmed present in
# tp_counts for billing_concentration/revenue_per_bene_outlier, and in
# `counted`) because this module's state file was never redirected during
# test runs (audit 2026-10-24; fixed in tests/conftest.py's state-module
# discovery). This exclusion stops the contamination from affecting any
# FUTURE weight computation. It deliberately does NOT edit or delete the
# existing on-disk record — see scripts/audit_feedback_contamination.py for a
# read-only report of the exact effect, left for Dave to review and apply.
_EXCLUDED_NPIS = {"1234567890"}

# In-memory state
_signal_fp_counts: dict[str, int] = {}  # signal -> false positive count
_signal_tp_counts: dict[str, int] = {}  # signal -> true positive count
_dismissals: list[dict] = []  # history of dismissed cases
_weight_adjustments: dict[str, float] = {}  # signal -> multiplier (0.5–1.0)
# npi -> "fp" | "tp": which direction this NPI has already been counted in.
# Without it, re-labelling a case (or a bulk update touching the same NPI twice)
# counts its signals again and again and quietly skews every multiplier.
_counted: dict[str, str] = {}
# npi -> the exact signal list credited the LAST time this NPI was counted.
# Reversing a label must undo using THIS snapshot, not whatever signals fire
# today — if a rescore/detector change altered the provider's current signals
# between the original label and the correction, undoing against today's
# signals silently leaves the original contribution uncorrected and can
# decrement signals that were never credited for this NPI (audit 2026-10-24).
_npi_signal_snapshot: dict[str, list[str]] = {}
# Append-only, immutable label-event log: {npi, direction, signals, timestamp}.
# Not yet the sole source of truth for the running counters (that would need
# a one-time migration of pre-existing `counted` entries, which have no
# recorded signal snapshot to replay — left as a reviewable follow-up), but
# every event recorded from here on carries its own signal snapshot, so
# rebuild_counts_from_events() can prove the running counters match history
# for anything labeled after this fix.
_events: list[dict] = []


def _load() -> None:
    """Load feedback data from disk."""
    global _signal_fp_counts, _signal_tp_counts, _dismissals, _weight_adjustments, _counted
    global _npi_signal_snapshot, _events
    try:
        if not _FEEDBACK_FILE.exists():
            return
        text = _FEEDBACK_FILE.read_text(encoding="utf-8").strip()
        if not text:
            return
        data = json.loads(text)
        _signal_fp_counts = data.get("fp_counts", {})
        _signal_tp_counts = data.get("tp_counts", {})
        _dismissals = data.get("dismissals", [])
        _weight_adjustments = data.get("weight_adjustments", {})
        _counted = data.get("counted", {})
        _npi_signal_snapshot = data.get("npi_signal_snapshot", {})
        _events = data.get("events", [])
        log.info("Loaded feedback data: %d FPs, %d TPs tracked",
                 sum(_signal_fp_counts.values()), sum(_signal_tp_counts.values()))
    except Exception as e:
        log.warning("Could not load feedback data: %s", e)


def _save() -> None:
    """Persist feedback data to disk."""
    try:
        atomic_write_json(_FEEDBACK_FILE, {
            "fp_counts": _signal_fp_counts,
            "tp_counts": _signal_tp_counts,
            "dismissals": _dismissals,
            "weight_adjustments": {sig: get_weight_adjustment(sig) for sig in all_signals},
            "counted": _counted,
            "npi_signal_snapshot": _npi_signal_snapshot,
            "events": _events,
            "updated_at": time.time(),
        })
    except Exception as e:
        log.warning("Could not save feedback data: %s", e)


def record_dismissal(npi: str, *, source: str = "analyst", evidence_reference: str = "") -> dict:
    """Record a dismissed case's fired signals as false positives (idempotent)."""
    return _apply(npi, "fp", source=source, evidence_reference=evidence_reference)


def record_confirmation(npi: str, *, source: str = "analyst", evidence_reference: str = "") -> dict:
    """Record a confirmed/reported case's fired signals as true positives (idempotent)."""
    return _apply(npi, "tp", source=source, evidence_reference=evidence_reference)


def _recalculate_weights() -> None:
    """
    Recalculate weight adjustment multipliers based on FP/TP ratios.

    A signal with many false positives relative to true positives gets
    dampened (multiplier < 1.0). Floor is 0.5 to prevent complete suppression.
    Signals need at least 5 total observations before adjustments kick in.
    """
    global _weight_adjustments
    all_signals = set(_signal_fp_counts.keys()) | set(_signal_tp_counts.keys())

    for sig in all_signals:
        fp = _signal_fp_counts.get(sig, 0)
        tp = _signal_tp_counts.get(sig, 0)
        total = fp + tp

        if total < 5:
            # Not enough data — keep weight at 1.0
            _weight_adjustments[sig] = 1.0
            continue

        # Precision = TP / (TP + FP)
        precision = tp / total if total > 0 else 0.5
        # Multiplier: scale between 0.5 (all FP) and 1.0 (all TP)
        multiplier = max(0.5, min(1.0, 0.5 + 0.5 * precision))
        _weight_adjustments[sig] = round(multiplier, 3)


def get_weight_adjustment(signal_name: str) -> float:
    """Get the weight multiplier for a signal (1.0 = no adjustment)."""
    # Analyst decisions and historical counters are not validated outcomes.
    # Only documented independent outcome events may adjust ranking weights.
    events = _verified_event_counts()
    fp, tp = events[0].get(signal_name, 0), events[1].get(signal_name, 0)
    return round(0.5 + 0.5 * tp / (fp + tp), 3) if fp + tp >= 5 else 1.0


def _verified_event_counts() -> tuple[dict, dict]:
    latest = {}
    for event in _events:
        if event.get("source") == "independent_outcome":
            latest[event["npi"]] = event
    counts = ({}, {})
    for npi, event in latest.items():
        if npi in _EXCLUDED_NPIS or not event.get("evidence_reference"):
            continue
        direction = event.get("direction")
        if direction not in ("fp", "tp"):
            continue
        target = counts[0 if direction == "fp" else 1]
        for signal in set(event.get("signals", [])):
            target[signal] = target.get(signal, 0) + 1
    return counts


def clear_label(npi: str, *, source: str = "analyst", evidence_reference: str = "") -> dict:
    return _apply(npi, "unlabeled", source=source, evidence_reference=evidence_reference)


def _active_signals(npi: str) -> list[str]:
    """The signals that fired for this NPI, from the scan cache or the case."""
    from core.store import get_provider_by_npi
    from core.review_store import get_review_item
    provider = get_provider_by_npi(npi)
    review = get_review_item(npi)
    sr = (provider or {}).get("signal_results") or (review or {}).get("signal_results") or []
    return [x.get("signal", "") for x in sr if x.get("flagged") and x.get("signal")]


def _apply(npi: str, direction: str, *, source: str = "analyst", evidence_reference: str = "") -> dict:
    """Count this NPI's fired signals as FP ('fp') or TP ('tp'), EXACTLY ONCE.

    Idempotent and reversible:
      - same direction again  -> no-op (a re-save or bulk update can't inflate counts)
      - opposite direction    -> the previous counts are backed out first, so a
                                 corrected label moves the evidence instead of
                                 double-counting it.
    """
    assert direction in ("fp", "tp", "unlabeled")
    if source == "independent_outcome" and direction != "unlabeled" and not evidence_reference.strip():
        raise ValueError("Independent outcome labels require an evidence reference")
    if npi in _EXCLUDED_NPIS:
        return {"recorded": False, "reason": f"{npi} is an excluded synthetic/test NPI"}
    prior = _counted.get(npi)
    prior_event = next((e for e in reversed(_events) if e.get("npi") == npi), {})
    if prior == direction and prior_event.get("source", "analyst") == source and prior_event.get("evidence_reference", "") == evidence_reference:
        return {"recorded": False, "reason": f"{npi} already counted as {direction}"}

    signals = sorted(set(_active_signals(npi))) if direction != "unlabeled" else []
    if not signals and direction != "unlabeled":
        return {"recorded": False, "reason": "No active signals found for this NPI"}

    if prior:  # reverse the earlier, now-superseded label — using the ORIGINAL
        # signal snapshot from when that label was made, not today's signals
        # (which may have drifted after a rescore). Legacy contributions without
        # snapshots remain auditable; never guess which counters to decrement.
        undo_signals = _npi_signal_snapshot.get(npi, [])
        undo = _signal_fp_counts if prior == "fp" else _signal_tp_counts
        for sig in undo_signals:
            if undo.get(sig):
                undo[sig] -= 1
                if undo[sig] <= 0:
                    undo.pop(sig, None)

    target = _signal_fp_counts if direction == "fp" else _signal_tp_counts
    for sig in signals:
        target[sig] = target.get(sig, 0) + 1
    if direction == "unlabeled":
        _counted.pop(npi, None)
        _npi_signal_snapshot.pop(npi, None)
    else:
        _counted[npi] = direction
        _npi_signal_snapshot[npi] = list(signals)
    _events.append({"npi": npi, "direction": direction, "signals": list(signals),
                     "timestamp": time.time(), "corrected_from": prior,
                     "schema_version": 2, "source": source, "evidence_reference": evidence_reference})

    if direction == "fp":
        _dismissals.append({"npi": npi, "signals": signals, "timestamp": time.time()})

    _recalculate_weights()
    _save()
    try:
        from core.gcs_sync import upload_file
        upload_file("feedback_data.json")
    except Exception:
        pass  # GCS optional; the local file is still written
    return {"recorded": True, "npi": npi, "direction": direction,
            "signals_recorded": signals, "corrected_from": prior}


def composite_with_feedback(signals: list[dict]) -> float:
    """Weighted composite with the learned per-signal multiplier applied.

    THE single place the feedback multiplier is applied — both scoring paths
    (scan_engine and risk_scorer) call this, so they cannot drift apart. Before
    this, get_weight_adjustment() had no callers at all: the whole feedback loop
    computed multipliers nothing ever used (audit 2026-07-25, #4).
    """
    return sum(
        s.get("score", 0) * s.get("weight", 0) * get_weight_adjustment(s.get("signal", ""))
        for s in signals
    )



def rebuild_counts_from_events() -> dict:
    """Recompute fp/tp counts purely from the immutable event log (last event
    per NPI wins, excluded NPIs dropped) and compare against the live running
    counters. Only covers NPIs labeled since the event log was added — legacy
    `counted` entries from before this fix have no recorded snapshot to
    replay. Used to prove reproducibility (relabel/rescore/reopen should never
    make the running counters disagree with the event history going forward),
    not to silently overwrite anything."""
    fp: dict[str, int] = {}
    tp: dict[str, int] = {}
    last_event_by_npi: dict[str, dict] = {}
    for ev in _events:
        if ev["npi"] in _EXCLUDED_NPIS:
            continue
        last_event_by_npi[ev["npi"]] = ev  # later events in the log supersede earlier ones
    for ev in last_event_by_npi.values():
        if ev["direction"] == "unlabeled":
            continue
        target = fp if ev["direction"] == "fp" else tp
        for sig in ev["signals"]:
            target[sig] = target.get(sig, 0) + 1
    return {
        "rebuilt_fp_counts": fp,
        "rebuilt_tp_counts": tp,
        "events_covered_npis": sorted(last_event_by_npi.keys()),
        "legacy_npis_not_covered": sorted(
            n for n in _counted if n not in last_event_by_npi and n not in _EXCLUDED_NPIS
        ),
    }


def get_feedback_summary() -> dict:
    """Return summary of feedback data for the UI."""
    if not _dismissals and not _signal_fp_counts:
        _load()

    all_signals = sorted(set(_signal_fp_counts.keys()) | set(_signal_tp_counts.keys()))
    signal_stats = []
    for sig in all_signals:
        fp = _signal_fp_counts.get(sig, 0)
        tp = _signal_tp_counts.get(sig, 0)
        total = fp + tp
        signal_stats.append({
            "signal": sig,
            "false_positives": fp,
            "true_positives": tp,
            "total": total,
            "precision": None,
            "analyst_agreement_rate": round(tp / total, 3) if total > 0 else None,
            "weight_adjustment": get_weight_adjustment(sig),
        })

    signal_stats.sort(key=lambda x: x["false_positives"], reverse=True)

    return {
        "label_definition": "Analyst assessments; these are not verified fraud outcomes",
        "sample_definition": "Selected reviewed providers, not a frozen top-50 evaluation",
        "precision_at_50": None,
        "independent_outcome_signal_counts": {"fp": _verified_event_counts()[0], "tp": _verified_event_counts()[1]},
        "total_dismissals": len(_dismissals),
        "total_fp_signals": sum(_signal_fp_counts.values()),
        "total_tp_signals": sum(_signal_tp_counts.values()),
        "signal_stats": signal_stats,
        "weight_adjustments": {sig: get_weight_adjustment(sig) for sig in all_signals},
    }


# Auto-load on import
_load()
