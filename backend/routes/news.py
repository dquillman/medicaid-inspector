"""
News & Legal Alerts API routes.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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

            # Classify + extract NPI. Uses Claude when NEWS_LLM_ENABLED is set,
            # otherwise falls back to keyword heuristics with identical behavior.
            from services.news_enrichment import classify_item
            classified = classify_item(title, summary)

            try:
                add_alert(
                    title=title,
                    source="HHS OIG",
                    url=link,
                    category=classified["category"],
                    summary=classified["summary"],
                    severity=classified["severity"],
                    npi=classified["npi"],
                    date=date_str,
                )
                added += 1
            except Exception as e:
                logger.warning("Failed to store HHS OIG alert '%s': %s", title, e)

        return {"ok": True, "fetched": added, "message": f"Added {added} alerts from HHS OIG feed"}

    except Exception as e:
        # Non-fatal — return error info but don't crash
        return {"ok": False, "fetched": 0, "message": f"Could not fetch HHS OIG feed: {str(e)}"}


class EnrichUrlBody(BaseModel):
    url: str
    source: str = "Manual"


@router.post("/enrich-url", dependencies=[Depends(require_admin)])
async def enrich_url(body: EnrichUrlBody):
    """
    Fetch a press-release URL, classify it with the news-enrichment agent,
    and propose an alert record. The alert is NOT saved automatically — the
    response is a draft for the admin to review and POST back to /api/news.
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(body.url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch URL: {e}")

    # Crude text extraction — strip tags. Keeps this endpoint dependency-free.
    import re as _re
    text = _re.sub(r"<script[\s\S]*?</script>", " ", html, flags=_re.I)
    text = _re.sub(r"<style[\s\S]*?</style>", " ", text, flags=_re.I)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()

    title_match = _re.search(r"<title>([^<]+)</title>", html, flags=_re.I)
    title = title_match.group(1).strip() if title_match else text[:120]

    from services.news_enrichment import enrich_from_text
    draft = enrich_from_text(
        title=title,
        source=body.source,
        url=body.url,
        summary=text[:2000],
    )
    return {"draft": draft}


# ── Provider-specific news endpoint (mounted under /api/providers) ───────────

provider_news_router = APIRouter(prefix="/api/providers", tags=["news"], dependencies=[Depends(require_user)])


@provider_news_router.get("/{npi}/news")
def provider_news(npi: str):
    """Get news/legal alerts associated with a specific provider NPI."""
    alerts = get_alerts(npi=npi)
    return {"npi": npi, "alerts": alerts, "total": len(alerts)}
