"""
News & Legal Alerts API routes.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.news_store import (
    get_alerts,
    add_alert,
    delete_alert,
    search_alerts,
    VALID_CATEGORIES,
    VALID_SEVERITIES,
)
from routes.auth import require_user, require_admin

router = APIRouter(prefix="/api/news", tags=["news"], dependencies=[Depends(require_user)])


class CreateAlertBody(BaseModel):
    title: str
    source: str
    url: str
    category: str
    summary: str
    severity: str = "medium"
    npi: Optional[str] = None
    date: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_alerts(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all alerts, filterable by category, severity, date range, or search text."""
    if search:
        alerts = search_alerts(search)
        # Apply additional filters on search results
        if category:
            alerts = [a for a in alerts if a["category"] == category]
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]
        return {"alerts": alerts, "total": len(alerts)}

    alerts = get_alerts(
        category=category,
        severity=severity,
        date_from=date_from,
        date_to=date_to,
    )
    return {"alerts": alerts, "total": len(alerts)}


@router.get("/categories")
def list_categories():
    """Return valid categories and severities."""
    return {
        "categories": sorted(VALID_CATEGORIES),
        "severities": sorted(VALID_SEVERITIES),
    }


@router.post("", dependencies=[Depends(require_admin)])
def create_alert(body: CreateAlertBody):
    """Manually add a news/legal alert."""
    try:
        alert = add_alert(
            title=body.title,
            source=body.source,
            url=body.url,
            category=body.category,
            summary=body.summary,
            severity=body.severity,
            npi=body.npi,
            date=body.date,
        )
        return {"ok": True, "alert": alert}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{alert_id}", dependencies=[Depends(require_admin)])
def remove_alert(alert_id: str):
    """Remove an alert by ID."""
    if not delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@router.post("/scan-hhs", dependencies=[Depends(require_admin)])
async def scan_hhs():
    """
    Fetch latest OIG enforcement actions from HHS.
    Parses the OIG press releases RSS feed. Non-fatal if it fails.
    """
    import httpx
    import xml.etree.ElementTree as ET

    feed_url = "https://oig.hhs.gov/rss/enforcement.xml"
    added = 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)

        # RSS 2.0 structure: rss > channel > item
        channel = root.find("channel")
        if channel is None:
            # Try Atom-style feed
            items = root.findall("item") or root.findall("{http://www.w3.org/2005/Atom}entry")
        else:
            items = channel.findall("item")

        for item in items[:50]:  # Limit to latest 50
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")

            title = title_el.text.strip() if title_el is not None and title_el.text else "Untitled"
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            summary = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
            pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else None

            # Parse date to ISO format
            date_str = None
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_date)
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = pub_date[:10] if len(pub_date) >= 10 else None

            # Determine category from title/summary
            text_lower = (title + " " + summary).lower()
            if any(w in text_lower for w in ["settlement", "settles", "agreed to pay"]):
                cat = "settlement"
            elif any(w in text_lower for w in ["enforcement", "indictment", "convicted", "sentenced", "charged"]):
                cat = "enforcement"
            elif any(w in text_lower for w in ["legal", "court", "ruling", "order", "injunction"]):
                cat = "legal"
            else:
                cat = "news"

            # Determine severity from keywords
            if any(w in text_lower for w in ["million", "convicted", "sentenced", "prison"]):
                sev = "critical"
            elif any(w in text_lower for w in ["indicted", "charged", "fraud scheme"]):
                sev = "high"
            elif any(w in text_lower for w in ["settlement", "agreed", "civil"]):
                sev = "medium"
            else:
                sev = "low"

            try:
                add_alert(
                    title=title,
                    source="HHS OIG",
                    url=link,
                    category=cat,
                    summary=summary[:500],
                    severity=sev,
                    date=date_str,
                )
                added += 1
            except Exception:
                pass

        return {"ok": True, "fetched": added, "message": f"Added {added} alerts from HHS OIG feed"}

    except Exception as e:
        # Non-fatal — return error info but don't crash
        return {"ok": False, "fetched": 0, "message": f"Could not fetch HHS OIG feed: {str(e)}"}


# ── Provider-specific news endpoint (mounted under /api/providers) ───────────

provider_news_router = APIRouter(prefix="/api/providers", tags=["news"], dependencies=[Depends(require_user)])


@provider_news_router.get("/{npi}/news")
def provider_news(npi: str):
    """Get news/legal alerts associated with a specific provider NPI."""
    alerts = get_alerts(npi=npi)
    return {"npi": npi, "alerts": alerts, "total": len(alerts)}
