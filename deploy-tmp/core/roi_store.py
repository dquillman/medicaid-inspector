"""
Persistent storage for ROI (Return on Investment) tracking.
Disk file: backend/roi_data.json
"""
import json
import time
import uuid
import pathlib
from typing import Optional
from collections import defaultdict
from datetime import datetime

from core.safe_io import atomic_write_json

_ROI_FILE = pathlib.Path(__file__).parent.parent / "roi_data.json"

# In-memory store: list of recovery records
_recoveries: list[dict] = []


# ── disk persistence ──────────────────────────────────────────────────────────

def load_roi_from_disk() -> None:
    global _recoveries
    try:
        if not _ROI_FILE.exists():
            return
        raw = json.loads(_ROI_FILE.read_text(encoding="utf-8"))
        _recoveries = raw.get("recoveries", [])
        print(f"[roi_store] Loaded {len(_recoveries)} recovery records from disk")
    except Exception as e:
        print(f"[roi_store] Could not load ROI data: {e}")


def save_roi_to_disk() -> None:
    try:
        atomic_write_json(_ROI_FILE, {"recoveries": _recoveries})
    except Exception as e:
        print(f"[roi_store] Could not save ROI data: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

def add_recovery(npi: str, amount: float, recovery_type: str, notes: str = "") -> dict:
    """Log a new recovery entry. Returns the created record."""
    record = {
        "id": str(uuid.uuid4()),
        "npi": npi,
        "amount_recovered": amount,
        "recovery_date": datetime.utcnow().isoformat(),
        "recovery_type": recovery_type,
        "notes": notes,
        "created_at": time.time(),
    }
    _recoveries.append(record)
    save_roi_to_disk()
    return record


def delete_recovery(recovery_id: str) -> bool:
    """Remove a recovery entry by ID. Returns True if found and removed."""
    global _recoveries
    before = len(_recoveries)
    _recoveries = [r for r in _recoveries if r["id"] != recovery_id]
    if len(_recoveries) < before:
        save_roi_to_disk()
        return True
    return False


# ── queries ───────────────────────────────────────────────────────────────────

def get_recoveries(page: int = 1, limit: int = 50) -> dict:
    """Return paginated recoveries sorted by date DESC."""
    sorted_recs = sorted(_recoveries, key=lambda r: r.get("created_at", 0), reverse=True)
    total = len(sorted_recs)
    start = (page - 1) * limit
    items = sorted_recs[start: start + limit]
    return {"items": items, "total": total, "page": page, "limit": limit}


def get_roi_summary() -> dict:
    """
    Compute ROI metrics from recoveries + review queue data.
    Returns summary dict with KPIs, monthly trends, and top recoveries.
    """
    from core.review_store import get_review_queue

    # Recovery totals
    total_recovered = sum(r["amount_recovered"] for r in _recoveries)

    # Review queue stats
    all_reviews = get_review_queue()
    confirmed = [r for r in all_reviews if r.get("status") == "confirmed_fraud"]
    referred = [r for r in all_reviews if r.get("status") == "referred"]
    dismissed = [r for r in all_reviews if r.get("status") == "dismissed"]

    cases_confirmed = len(confirmed)
    cases_referred = len(referred)
    cases_dismissed = len(dismissed)

    # Total flagged billing = total_paid for confirmed + referred cases
    total_flagged_billing = sum(r.get("total_paid", 0) for r in confirmed + referred)

    # Recovery rate
    recovery_rate = (total_recovered / total_flagged_billing) if total_flagged_billing > 0 else 0.0

    # False positive rate
    resolved_total = cases_dismissed + cases_confirmed + cases_referred
    false_positive_rate = (cases_dismissed / resolved_total) if resolved_total > 0 else 0.0

    # Average time to resolution (days between added_at and updated_at for resolved cases)
    resolved_cases = confirmed + referred + dismissed
    resolution_times = []
    for case in resolved_cases:
        added = case.get("added_at", 0)
        updated = case.get("updated_at", 0)
        if added > 0 and updated > added:
            days = (updated - added) / 86400  # seconds to days
            resolution_times.append(days)
    avg_time_to_resolution = (
        sum(resolution_times) / len(resolution_times) if resolution_times else 0.0
    )

    # Monthly trend: recoveries aggregated by month
    monthly: dict[str, float] = defaultdict(float)
    for r in _recoveries:
        date_str = r.get("recovery_date", "")
        if date_str:
            month_key = date_str[:7]  # YYYY-MM
            monthly[month_key] += r["amount_recovered"]
    monthly_trend = [
        {"month": k, "amount": v}
        for k, v in sorted(monthly.items())
    ]

    # Top 10 recoveries by amount
    top_recoveries = sorted(_recoveries, key=lambda r: r["amount_recovered"], reverse=True)[:10]

    return {
        "total_recovered": round(total_recovered, 2),
        "total_flagged_billing": round(total_flagged_billing, 2),
        "recovery_rate": round(recovery_rate, 4),
        "cases_confirmed": cases_confirmed,
        "cases_referred": cases_referred,
        "cases_dismissed": cases_dismissed,
        "false_positive_rate": round(false_positive_rate, 4),
        "avg_time_to_resolution": round(avg_time_to_resolution, 2),
        "monthly_trend": monthly_trend,
        "top_recoveries": top_recoveries,
    }
