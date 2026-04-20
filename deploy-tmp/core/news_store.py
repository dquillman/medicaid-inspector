"""
Persistent storage for news/legal alerts.
Disk file: backend/news_alerts.json
"""
import json
import time
import uuid
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

_ALERTS_FILE = pathlib.Path(__file__).parent.parent / "news_alerts.json"

# In-memory store: id -> alert dict
_alerts: dict[str, dict] = {}

VALID_CATEGORIES = {"news", "legal", "enforcement", "settlement"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


# ── disk persistence ──────────────────────────────────────────────────────────

def load_news_from_disk() -> None:
    global _alerts
    try:
        if not _ALERTS_FILE.exists():
            return
        raw = json.loads(_ALERTS_FILE.read_text(encoding="utf-8"))
        _alerts = {item["id"]: item for item in raw.get("alerts", [])}
        print(f"[news_store] Loaded {len(_alerts)} news alerts from disk")
    except Exception as e:
        print(f"[news_store] Could not load news alerts: {e}")


def save_news_to_disk() -> None:
    try:
        atomic_write_json(_ALERTS_FILE, {"alerts": list(_alerts.values())})
    except Exception as e:
        print(f"[news_store] Could not save news alerts: {e}")


# ── mutations ─────────────────────────────────────────────────────────────────

def add_alert(
    title: str,
    source: str,
    url: str,
    category: str,
    summary: str,
    severity: str = "medium",
    npi: Optional[str] = None,
    date: Optional[str] = None,
) -> dict:
    """Add a news/legal alert. Returns the new alert dict."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {category!r}. Must be one of {VALID_CATEGORIES}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"Invalid severity: {severity!r}. Must be one of {VALID_SEVERITIES}")

    alert_id = uuid.uuid4().hex[:12]
    now = time.time()
    alert = {
        "id": alert_id,
        "npi": npi,
        "title": title,
        "source": source,
        "url": url,
        "date": date or time.strftime("%Y-%m-%d"),
        "category": category,
        "summary": summary,
        "severity": severity,
        "created_at": now,
    }
    _alerts[alert_id] = alert
    save_news_to_disk()
    return alert


def delete_alert(alert_id: str) -> bool:
    """Delete an alert by ID. Returns True if deleted, False if not found."""
    if alert_id not in _alerts:
        return False
    del _alerts[alert_id]
    save_news_to_disk()
    return True


# ── queries ───────────────────────────────────────────────────────────────────

def get_alerts(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    npi: Optional[str] = None,
) -> list[dict]:
    """Return alerts sorted by date DESC, optionally filtered."""
    items = list(_alerts.values())

    if category:
        items = [a for a in items if a["category"] == category]
    if severity:
        items = [a for a in items if a["severity"] == severity]
    if npi:
        items = [a for a in items if a.get("npi") == npi]
    if date_from:
        items = [a for a in items if a.get("date", "") >= date_from]
    if date_to:
        items = [a for a in items if a.get("date", "") <= date_to]

    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return items


def search_alerts(query: str) -> list[dict]:
    """Search alerts by title or summary text (case-insensitive)."""
    q = query.lower()
    results = [
        a for a in _alerts.values()
        if q in a.get("title", "").lower() or q in a.get("summary", "").lower()
    ]
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results


def get_alert_by_id(alert_id: str) -> Optional[dict]:
    """Return a single alert by ID."""
    return _alerts.get(alert_id)
