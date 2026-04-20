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


def _load() -> None:
    """Load feedback data from disk."""
    global _signal_fp_counts, _signal_tp_counts, _dismissals, _weight_adjustments
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
            "updated_at": time.time(),
        })
    except Exception as e:
        log.warning("Could not save feedback data: %s", e)


def record_dismissal(npi: str) -> dict:
    """
    Record a dismissed case's active signals as false positives.
    Recalculates weight adjustments after recording.
    """
    from core.store import get_provider_by_npi
    from core.review_store import get_review_item

    provider = get_provider_by_npi(npi)
    review = get_review_item(npi)

    # Get active signals from either source
    signal_results = []
    if provider and provider.get("signal_results"):
        signal_results = provider["signal_results"]
    elif review and review.get("signal_results"):
        signal_results = review["signal_results"]

    active_signals = [s.get("signal", "") for s in signal_results if s.get("flagged")]

    if not active_signals:
        return {"recorded": False, "reason": "No active signals found for dismissed NPI"}

    # Record each active signal as a false positive
    for sig in active_signals:
        _signal_fp_counts[sig] = _signal_fp_counts.get(sig, 0) + 1

    _dismissals.append({
        "npi": npi,
        "signals": active_signals,
        "timestamp": time.time(),
        "risk_score": (provider or {}).get("risk_score", 0),
    })

    # Recalculate weight adjustments
    _recalculate_weights()
    _save()

    return {
        "recorded": True,
        "npi": npi,
        "signals_recorded": active_signals,
        "total_dismissals": len(_dismissals),
    }


def record_confirmation(npi: str) -> dict:
    """
    Record a confirmed fraud case's active signals as true positives.
    """
    from core.store import get_provider_by_npi
    from core.review_store import get_review_item

    provider = get_provider_by_npi(npi)
    review = get_review_item(npi)

    signal_results = []
    if provider and provider.get("signal_results"):
        signal_results = provider["signal_results"]
    elif review and review.get("signal_results"):
        signal_results = review["signal_results"]

    active_signals = [s.get("signal", "") for s in signal_results if s.get("flagged")]

    for sig in active_signals:
        _signal_tp_counts[sig] = _signal_tp_counts.get(sig, 0) + 1

    _recalculate_weights()
    _save()

    return {
        "recorded": True,
        "npi": npi,
        "signals_recorded": active_signals,
    }


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
