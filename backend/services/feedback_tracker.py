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

# In-memory state
_signal_fp_counts: dict[str, int] = {}  # signal -> false positive count
_signal_tp_counts: dict[str, int] = {}  # signal -> true positive count
_dismissals: list[dict] = []  # history of dismissed cases
_weight_adjustments: dict[str, float] = {}  # signal -> multiplier (0.5–1.0)
# npi -> "fp" | "tp": which direction this NPI has already been counted in.
# Without it, re-labelling a case (or a bulk update touching the same NPI twice)
# counts its signals again and again and quietly skews every multiplier.
_counted: dict[str, str] = {}


def _load() -> None:
    """Load feedback data from disk."""
    global _signal_fp_counts, _signal_tp_counts, _dismissals, _weight_adjustments, _counted
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
            "weight_adjustments": _weight_adjustments,
            "counted": _counted,
            "updated_at": time.time(),
        })
    except Exception as e:
        log.warning("Could not save feedback data: %s", e)


def record_dismissal(npi: str) -> dict:
    """Record a dismissed case's fired signals as false positives (idempotent)."""
    return _apply(npi, "fp")


def record_confirmation(npi: str) -> dict:
    """Record a confirmed/reported case's fired signals as true positives (idempotent)."""
    return _apply(npi, "tp")


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
    if not _weight_adjustments:
        _load()
    return _weight_adjustments.get(signal_name, 1.0)

def _active_signals(npi: str) -> list[str]:
    """The signals that fired for this NPI, from the scan cache or the case."""
    from core.store import get_provider_by_npi
    from core.review_store import get_review_item
    provider = get_provider_by_npi(npi)
    review = get_review_item(npi)
    sr = (provider or {}).get("signal_results") or (review or {}).get("signal_results") or []
    return [x.get("signal", "") for x in sr if x.get("flagged") and x.get("signal")]


def _apply(npi: str, direction: str) -> dict:
    """Count this NPI's fired signals as FP ('fp') or TP ('tp'), EXACTLY ONCE.

    Idempotent and reversible:
      - same direction again  -> no-op (a re-save or bulk update can't inflate counts)
      - opposite direction    -> the previous counts are backed out first, so a
                                 corrected label moves the evidence instead of
                                 double-counting it.
    """
    assert direction in ("fp", "tp")
    prior = _counted.get(npi)
    if prior == direction:
        return {"recorded": False, "reason": f"{npi} already counted as {direction}"}

    signals = _active_signals(npi)
    if not signals:
        return {"recorded": False, "reason": "No active signals found for this NPI"}

    if prior:  # reverse the earlier, now-superseded label
        undo = _signal_fp_counts if prior == "fp" else _signal_tp_counts
        for sig in signals:
            if undo.get(sig):
                undo[sig] -= 1
                if undo[sig] <= 0:
                    undo.pop(sig, None)

    target = _signal_fp_counts if direction == "fp" else _signal_tp_counts
    for sig in signals:
        target[sig] = target.get(sig, 0) + 1
    _counted[npi] = direction

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
            "precision": round(tp / total, 3) if total > 0 else None,
            "weight_adjustment": _weight_adjustments.get(sig, 1.0),
        })

    signal_stats.sort(key=lambda x: x["false_positives"], reverse=True)

    return {
        "total_dismissals": len(_dismissals),
        "total_fp_signals": sum(_signal_fp_counts.values()),
        "total_tp_signals": sum(_signal_tp_counts.values()),
        "signal_stats": signal_stats,
        "weight_adjustments": _weight_adjustments,
    }


# Auto-load on import
_load()
