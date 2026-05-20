"""
LLM-assisted enrichment of investigation narratives.

This module wraps the deterministic template output from
`services.narrative_generator.generate_narrative()` and asks Claude to
re-render the prose sections into a more cohesive investigation memo.
The structured `sections` list (with regulatory citations) is preserved
unchanged so downstream consumers (PDF export, MFCU referral packets)
keep working when LLM enrichment is disabled or fails.

PHI handling
------------
Provider data passed to this module is Medicaid claims data, which is
PHI under HIPAA. Calling an external LLM with PHI requires a Business
Associate Agreement (BAA) with the vendor. To prevent accidentally
shipping PHI to a non-BAA endpoint, this module refuses to call out
unless BOTH of these env vars are set:

    NARRATIVE_LLM_ENABLED=true
    ANTHROPIC_BAA_ACK=true           # operator asserts a BAA is in place

If either is missing, the original template narrative is returned
verbatim and a log line is emitted. The BAA ack is a deliberate
speed bump — do not remove it.

Recommended deployment: Anthropic models via AWS Bedrock or Google
Vertex AI under your existing cloud BAA. Set ANTHROPIC_BASE_URL to the
appropriate proxy when using those.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from services.narrative_generator import generate_narrative as _generate_template

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are a Medicaid program-integrity analyst drafting investigation \
memos for state Medicaid Fraud Control Units (MFCUs) and the HHS Office \
of Inspector General. You write in the formal, neutral register used in \
official referral packages: no speculation beyond the evidence, no \
sensational language, no recommendations that exceed what the structured \
findings support.

You will receive a set of structured findings about one provider, \
including risk signals (each with a regulatory citation), billing \
aggregates, and pattern detections. Re-render these findings into a \
cohesive investigation narrative.

Hard constraints:
- Preserve every numerical figure exactly as given. Do not round, \
  recompute, or invent statistics.
- Preserve every regulatory citation. Cite them inline where the \
  corresponding signal is discussed.
- Do not introduce facts not present in the input. If a section is \
  empty, say so plainly rather than speculating.
- Output plain text only. No markdown headings, no bullet decoration \
  beyond standard hyphens, no emoji.
- Maintain the section ordering and section titles from the input.
- Use the heading format: "N. SECTION TITLE" followed by a 40-character \
  rule of hyphens, matching the template's existing format.
"""


def _client():
    """Lazily import and construct the Anthropic client."""
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "anthropic SDK not installed. Add 'anthropic' to requirements.txt "
            "and reinstall before enabling NARRATIVE_LLM_ENABLED."
        ) from e
    return anthropic.Anthropic()


def _llm_enabled() -> tuple[bool, str]:
    """Return (enabled, reason_if_disabled)."""
    if os.environ.get("NARRATIVE_LLM_ENABLED", "").lower() not in ("1", "true", "yes"):
        return False, "NARRATIVE_LLM_ENABLED not set"
    if os.environ.get("ANTHROPIC_BAA_ACK", "").lower() not in ("1", "true", "yes"):
        return False, "ANTHROPIC_BAA_ACK not set (PHI guardrail)"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY not set"
    return True, ""


def _sections_to_findings_block(sections: list[dict]) -> str:
    """Render the structured sections as a single findings block the model can read."""
    parts = []
    for i, sec in enumerate(sections, 1):
        parts.append(f"--- SECTION {i}: {sec['title'].upper()} ---")
        parts.append(sec.get("content", "").strip())
        parts.append("")
    return "\n".join(parts)


def _call_claude(sections: list[dict], npi: str) -> str:
    """Single Anthropic call. Returns the rewritten narrative body (no header)."""
    client = _client()
    model = os.environ.get("NARRATIVE_LLM_MODEL", "claude-opus-4-7")

    findings = _sections_to_findings_block(sections)
    user_msg = (
        f"Subject NPI: {npi}\n\n"
        f"Findings to render:\n\n{findings}\n\n"
        "Produce the narrative body now. Begin with section 1; do not include "
        "the document header (the caller will prepend it)."
    )

    # System prompt is cacheable — it doesn't change per-request and is large.
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(text_parts).strip()


def generate_narrative_enhanced(
    npi: str,
    force_template: bool = False,
    provider_override: dict | None = None,
) -> dict:
    """
    Generate a narrative, optionally enriched by Claude.

    Always returns the same shape as `generate_narrative()` plus a
    `source` field ("template" or "llm") so the caller can tell what
    happened. The deterministic `sections` list is always present and
    unchanged.

    Args:
        provider_override: Pre-enriched provider dict (slim cache merged
            with live DuckDB aggregates).  Passed through to the template
            generator so narratives are accurate even on Cloud Run where
            the slim cache lacks computed fields.
    """
    base = _generate_template(npi, provider_override=provider_override)
    base = {**base, "source": "template"}

    if force_template:
        return base

    enabled, reason = _llm_enabled()
    if not enabled:
        log.debug("Narrative LLM disabled: %s", reason)
        return base

    try:
        t0 = time.time()
        body = _call_claude(base["sections"], npi)
        elapsed_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        # Any failure (network, rate limit, parse) falls back silently.
        log.warning("Narrative LLM enrichment failed, falling back to template: %s", e)
        return base

    if not body or len(body) < 200:
        log.warning("LLM returned suspiciously short narrative (%d chars); falling back", len(body))
        return base

    # Stitch the LLM body under the original header so downstream
    # consumers see the same document shell.
    header_end = base["narrative"].find("\n", base["narrative"].find("=" * 72))
    header = base["narrative"][: header_end + 1] if header_end > 0 else ""
    enhanced_narrative = header + "\n" + body

    return {
        **base,
        "narrative": enhanced_narrative,
        "word_count": len(enhanced_narrative.split()),
        "source": "llm",
        "llm_elapsed_ms": elapsed_ms,
    }
