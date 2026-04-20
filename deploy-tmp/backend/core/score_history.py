"""
Persistent storage for risk-score snapshots over time.
Disk file: backend/score_history.json

Records a snapshot after each scan batch so we can visualise score trends,
detect biggest movers, and show system-wide distribution changes.
"""
import json
import time
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

_HISTORY_FILE = pathlib.Path(__file__).parent.parent / "score_history.json"

# NPI -> list of snapshot dicts (most recent last)
_history: dict[str, list[dict]] = {}

MAX_SNAPSHOTS_PER_PROVIDER = 100


# ── disk persistence ──────────────────────────────────────────────────────────

def load_history_from_disk() -> None:
    global _history
    try:
        if not _HISTORY_FILE.exists():
            return
        raw = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        _history = raw.get("history", {})
        total = sum(len(v) for v in _history.values())
        print(f"[score_history] Loaded {total} snapshots for {len(_history)} providers")
    except Exception as e:
        print(f"[score_history] Could not load history: {e}")


def save_history_to_disk() -> None:
    try:
        atomic_write_json(_HISTORY_FILE, {"history": _history})
    except Exception as e:
        print(f"[score_history] Could not save history: {e}")


# ── recording ─────────────────────────────────────────────────────────────────

def record_snapshot(npi: str, risk_score: float, flag_count: int, total_paid: float) -> None:
    """Record a single provider score snapshot. Called after scan batch completes."""
    snap = {
        "timestamp": time.time(),
        "score": round(risk_score, 1),
        "flags": flag_count,
        "total_paid": round(total_paid, 2),
    }
    if npi not in _history:
        _history[npi] = []
    _history[npi].append(snap)
    # Keep only last N snapshots
    if len(_history[npi]) > MAX_SNAPSHOTS_PER_PROVIDER:
        _history[npi] = _history[npi][-MAX_SNAPSHOTS_PER_PROVIDER:]


def record_batch_snapshots(results: list[dict]) -> None:
    """Record snapshots for a whole batch of scan results, then persist once."""
    for r in results:
        npi = r.get("npi")
        if not npi:
            continue
        score = r.get("risk_score", 0.0)
        flags = len([f for f in r.get("flags", []) if f.get("flagged", True)])
        total_paid = r.get("total_paid", 0.0)
        record_snapshot(npi, score, flags, total_paid)
    save_history_to_disk()


# ── queries ───────────────────────────────────────────────────────────────────

def get_history(npi: str) -> list[dict]:
    """Return all snapshots for a given NPI, oldest first."""
    return _history.get(npi, [])


def get_movers(top_n: int = 10) -> dict:
    """
    Find providers with the biggest score changes between their two most recent
    snapshots. Returns dict with 'rising' and 'falling' lists.
    """
    deltas: list[dict] = []
    for npi, snaps in _history.items():
        if len(snaps) < 2:
            continue
        latest = snaps[-1]
        previous = snaps[-2]
        delta = latest["score"] - previous["score"]
        if delta == 0:
            continue
        deltas.append({
            "npi": npi,
            "previous_score": previous["score"],
            "current_score": latest["score"],
            "delta": round(delta, 1),
            "previous_timestamp": previous["timestamp"],
            "current_timestamp": latest["timestamp"],
            "current_flags": latest["flags"],
            "total_paid": latest["total_paid"],
        })

    # Sort: rising = biggest positive delta, falling = biggest negative delta
    rising = sorted([d for d in deltas if d["delta"] > 0], key=lambda d: d["delta"], reverse=True)[:top_n]
    falling = sorted([d for d in deltas if d["delta"] < 0], key=lambda d: d["delta"])[:top_n]

    return {"rising": rising, "falling": falling}


def get_summary() -> dict:
    """
    System-wide score distribution summary over time.
    Groups snapshots by approximate time bucket (hourly) and computes
    distribution stats for each bucket.
    """
    if not _history:
        return {"buckets": [], "total_providers": 0}

    # Collect all snapshots with timestamps
    all_snaps: list[dict] = []
    for npi, snaps in _history.items():
        for s in snaps:
            all_snaps.append({**s, "npi": npi})

    if not all_snaps:
        return {"buckets": [], "total_providers": 0}

    all_snaps.sort(key=lambda s: s["timestamp"])

    # Bucket by hour
    HOUR = 3600
    buckets: list[dict] = []
    current_bucket_start = None
    current_scores: list[float] = []
    current_npis: set = set()

    for snap in all_snaps:
        bucket_start = int(snap["timestamp"] // HOUR) * HOUR
        if current_bucket_start is None:
            current_bucket_start = bucket_start

        if bucket_start != current_bucket_start:
            # Flush
            if current_scores:
                sorted_scores = sorted(current_scores)
                n = len(sorted_scores)
                buckets.append({
                    "timestamp": current_bucket_start,
                    "provider_count": len(current_npis),
                    "avg_score": round(sum(sorted_scores) / n, 1),
                    "median_score": round(sorted_scores[n // 2], 1),
                    "high_risk_count": sum(1 for s in sorted_scores if s >= 50),
                    "flagged_count": sum(1 for s in sorted_scores if s > 10),
                })
            current_bucket_start = bucket_start
            current_scores = []
            current_npis = set()

        current_scores.append(snap["score"])
        current_npis.add(snap["npi"])

    # Flush last bucket
    if current_scores:
        sorted_scores = sorted(current_scores)
        n = len(sorted_scores)
        buckets.append({
            "timestamp": current_bucket_start,
            "provider_count": len(current_npis),
            "avg_score": round(sum(sorted_scores) / n, 1),
            "median_score": round(sorted_scores[n // 2], 1),
            "high_risk_count": sum(1 for s in sorted_scores if s >= 50),
            "flagged_count": sum(1 for s in sorted_scores if s > 10),
        })

    return {
        "buckets": buckets,
        "total_providers": len(_history),
    }
