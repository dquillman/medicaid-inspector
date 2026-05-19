"""
LLM-assisted enrichment of OIG / DOJ news items.

The existing `routes.news.scan_hhs` endpoint parses the HHS OIG RSS
feed and classifies each item by keyword matching:

    title contains "settlement" -> category="settlement"
    title contains "million"    -> severity="critical"
    ...

That heuristic is OK for an MVP but it routinely mislabels items and
never extracts the subject NPI (which is what links an enforcement
action back to a provider in this database). This module replaces the
keyword classifier with a Claude call that:

  1. classifies the item into one of VALID_CATEGORIES
  2. assigns a severity in VALID_SEVERITIES
  3. extracts the subject NPI if one appears in the title/summary
  4. writes a tighter one-paragraph summary

Unlike the narrative module, the input here is *public* press-release
text — not PHI — so there is no BAA gate. There is still an enable
flag (`NEWS_LLM_ENABLED`) and a graceful fallback to the original
keyword classifier when disabled or when the call fails, so this
module is safe to ship dark and turn on per-deployment.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from core.news_store import VALID_CATEGORIES, VALID_SEVERITIES

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You classify HHS-OIG and DOJ press releases for a Medicaid fraud \
detection system.

For each item, return a single JSON object with these keys:

  category   one of: news, legal, enforcement, settlement
  severity   one of: low, medium, high, critical
  npi        a 10-digit National Provider Identifier if one is \
             explicitly stated in the text, otherwise null
  summary    a single-paragraph (<= 80 words) neutral summary, \
             preserving dollar amounts and the alleged conduct

Severity rubric:
  critical   criminal conviction, prison sentence, or >$10M settlement
  high       criminal indictment, large civil settlement, exclusion of \
             a high-volume provider
  medium     civil settlement under $10M, single-provider exclusion
  low        guidance, advisory, or unrelated agency news

Category rubric:
  settlement  any civil monetary resolution
  enforcement criminal action: indictment, conviction, sentencing
  legal       court rulings, injunctions, appellate decisions
  news        everything else (guidance, advisories, agency news)

Output JSON only. No prose, no code fence."""


def _client():
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise RuntimeError("anthropic SDK not installed") from e
    return anthropic.Anthropic()


def _enabled() -> bool:
    return (
        os.environ.get("NEWS_LLM_ENABLED", "").lower() in ("1", "true", "yes")
        and bool(os.environ.get("ANTHROPIC_API_KEY"))
    )


_NPI_RE = re.compile(r"\b(\d{10})\b")


def _heuristic_classify(title: str, summary: str) -> dict:
    """Keyword classifier — same logic the route already uses, lifted here for reuse."""
    text_lower = (title + " " + summary).lower()
    if any(w in text_lower for w in ["settlement", "settles", "agreed to pay"]):
        cat = "settlement"
    elif any(w in text_lower for w in ["enforcement", "indictment", "convicted", "sentenced", "charged"]):
        cat = "enforcement"
    elif any(w in text_lower for w in ["legal", "court", "ruling", "order", "injunction"]):
        cat = "legal"
    else:
        cat = "news"

    if any(w in text_lower for w in ["million", "convicted", "sentenced", "prison"]):
        sev = "critical"
    elif any(w in text_lower for w in ["indicted", "charged", "fraud scheme"]):
        sev = "high"
    elif any(w in text_lower for w in ["settlement", "agreed", "civil"]):
        sev = "medium"
    else:
        sev = "low"

    m = _NPI_RE.search(title + " " + summary)
    return {
        "category": cat,
        "severity": sev,
        "npi": m.group(1) if m else None,
        "summary": summary[:500],
    }


def _validate(item: dict, fallback: dict) -> dict:
    """Validate model output and fall back field-by-field if anything is off."""
    out = dict(fallback)
    if item.get("category") in VALID_CATEGORIES:
        out["category"] = item["category"]
    if item.get("severity") in VALID_SEVERITIES:
        out["severity"] = item["severity"]
    npi = item.get("npi")
    if isinstance(npi, str) and _NPI_RE.fullmatch(npi):
        out["npi"] = npi
    summary = item.get("summary")
    if isinstance(summary, str) and 10 <= len(summary) <= 800:
        out["summary"] = summary
    return out


def classify_item(title: str, summary: str) -> dict:
    """
    Classify a single press release.

    Returns: {category, severity, npi, summary}
    Falls back to keyword heuristics on any failure.
    """
    fallback = _heuristic_classify(title, summary)
    if not _enabled():
        return fallback

    try:
        client = _client()
        model = os.environ.get("NEWS_LLM_MODEL", "claude-haiku-4-5-20251001")
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{
                "role": "user",
                "content": f"Title: {title}\n\nSummary: {summary}",
            }],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        # Be lenient: strip code fences if the model produced any despite instructions.
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
    except Exception as e:
        log.warning("News LLM classification failed (%s); using heuristic", e)
        return fallback

    return _validate(parsed, fallback)


def enrich_from_text(title: str, source: str, url: str, summary: str, date: Optional[str] = None) -> dict:
    """
    One-shot helper: classify + return a dict ready for `add_alert(**result)`.
    """
    classified = classify_item(title, summary)
    return {
        "title": title,
        "source": source,
        "url": url,
        "category": classified["category"],
        "severity": classified["severity"],
        "summary": classified["summary"],
        "npi": classified["npi"],
        "date": date,
    }
