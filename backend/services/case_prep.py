"""
Case preparation — automates steps 2–6 of the investigation workflow so a
Fraud Brain lead arrives in the Review Queue evidence-gathered and packet-ready.

    prepare_case(npi)
      2. reads the lead's evidence (Brain board entry: intensity multiple,
         top codes, fired signals)
      3. corroborates: ego network (ring ties to other flagged NPIs) +
         claim-level patterns + the Brain's own corroboration sources
      4. opens the case at Under Review with the auto-note (intensity + codes)
      5. appends an AI-authored, timestamped case note with everything found —
         including "no corroboration found", which is also evidence
      6. validates the referral packet builds and attaches it to the case

What it deliberately does NOT do: confirm, submit, or report anything. Those
transitions (confirmed / tip_filed / referred) are human-gated in
review_store.set_queue_status and stay that way — the analyst reads the packet,
decides, submits at tips.oig.hhs.gov, and clicks Reported themselves.

The nightly auto-prepare (see routes/review.py) calls this for exactly ONE
provider per day — the #1 fresh unworked Brain lead — matching Dave's
one-submission-per-day pace.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# Cap the whole preparation; every sub-step is individually best-effort.
NETWORK_TIMEOUT_S = 50
PACKET_TIMEOUT_S = 90

# A neighbor in the billing network only counts as a "ring tie" worth flagging
# when it is itself a scored, elevated-risk provider in our cache.
RING_NEIGHBOR_MIN_RISK = 40.0


def _brain_entry(npi: str) -> dict | None:
    """This NPI's entry on the current Brain board (None if off-board)."""
    try:
        from services.fraud_brain import get_top_frauds
        board = get_top_frauds(limit=10)
        return next((e for e in board.get("top", []) if e.get("npi") == npi), None)
    except Exception:  # noqa: BLE001
        logger.warning("case_prep: brain board unavailable", exc_info=True)
        return None


def _auto_note(provider: dict, entry: dict | None) -> str:
    """The one-line capture note: intensity multiple + the codes (step 4)."""
    parts: list[str] = []
    for ev in (entry or {}).get("evidence", []):
        if "intensity" in (ev.get("source") or "").lower():
            parts.append(ev.get("detail", ""))
            break
    top_hcpcs = provider.get("top_hcpcs") or ""
    if top_hcpcs:
        parts.append(f"Top code: {top_hcpcs}")
    flagged = [s.get("signal", "") for s in (provider.get("signal_results")
               or provider.get("flags") or []) if s.get("flagged")]
    if flagged:
        parts.append(f"{len(flagged)} signals fired: " + ", ".join(flagged[:6])
                     + ("…" if len(flagged) > 6 else ""))
    return " | ".join(p for p in parts if p) or "Auto-prepared from Fraud Brain lead."


async def _corroborate_network(npi: str) -> list[str]:
    """Ego-network check: who does this NPI bill with, and are any of those
    neighbors themselves elevated-risk in our cache (a ring signature)?"""
    from core.store import get_provider_by_npi
    from routes.network import get_network
    try:
        net = await asyncio.wait_for(get_network(npi), timeout=NETWORK_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — 404/timeout/etc all mean "no network evidence"
        return [f"Network: not checkable right now ({type(exc).__name__}) — check the Network page manually."]
    edges = net.get("edges") or []
    if not edges:
        return ["Network: no billing/servicing relationships with other NPIs — bills alone (no ring structure)."]
    lines = [f"Network: {len(edges)} billing relationship(s) with other NPIs."]
    risky = []
    for e in sorted(edges, key=lambda x: -(x.get("weight") or 0))[:25]:
        other = e["source"] if e["target"] == npi else e["target"]
        p = get_provider_by_npi(other)
        if p and float(p.get("risk_score") or 0) >= RING_NEIGHBOR_MIN_RISK:
            risky.append(f"  - RING TIE? NPI {other} ({p.get('provider_name') or 'unnamed'}) "
                         f"risk {float(p.get('risk_score') or 0):.0f}, "
                         f"${(e.get('weight') or 0):,.0f} between them")
    if risky:
        lines.append(f"{len(risky)} neighbor(s) are themselves flagged elevated-risk:")
        lines += risky[:5]
    else:
        lines.append("No flagged co-billers found among top relationships — no ring evidence.")
    return lines


async def _corroborate_claim_patterns(npi: str) -> list[str]:
    """Claim-level pattern hits (unbundling, duplicates, impossible days…)."""
    try:
        from services.claim_patterns import get_provider_claim_patterns
        res = await asyncio.wait_for(get_provider_claim_patterns(npi), timeout=NETWORK_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return [f"Claim patterns: not checkable right now ({type(exc).__name__})."]
    pats = res.get("patterns") if isinstance(res, dict) else res
    if not pats:
        return ["Claim patterns: no unbundling / duplicate / impossible-day hits."]
    lines = [f"Claim patterns: {len(pats)} hit(s):"]
    for p in pats[:6]:
        if isinstance(p, dict):
            kind = p.get("pattern_type") or p.get("type") or "pattern"
            detail = p.get("description") or p.get("detail") or ""
            lines.append(f"  - {kind}: {detail}"[:200])
    return lines


def _corroborate_brain(entry: dict | None) -> list[str]:
    """The Brain's own corroboration evidence (external sources, exclusns…)."""
    if not entry:
        return ["Brain board: provider not on the current top-10 board (prepared directly)."]
    lines = [f"Brain score {entry.get('brain_score')} — recency: {entry.get('recency') or 'n/a'}, "
             f"${(entry.get('total_paid') or 0):,.0f} total paid."]
    for ev in entry.get("evidence", []):
        src = (ev.get("source") or "")
        if any(k in src.lower() for k in ("corrobor", "exclusion", "deactivated", "intensity")):
            lines.append(f"  - {src}: {ev.get('detail','')}"[:250])
    return lines


async def prepare_case(npi: str, *, actor: str = "case-prep") -> dict:
    """Run the full preparation for one NPI. Returns a result summary dict.
    Never raises for evidence-gathering failures — each section degrades to an
    honest 'not checkable' line in the case note."""
    from core.store import get_provider_by_npi
    from core.review_store import (add_case_note, add_document, add_to_review_queue,
                                   get_review_item, mark_prepared, set_queue_status)

    t0 = time.time()
    provider = get_provider_by_npi(npi)
    if not provider:
        return {"ok": False, "npi": npi, "error": "provider not in scan cache"}

    existing = get_review_item(npi)
    if existing and existing.get("prepared_at"):
        return {"ok": False, "npi": npi, "error": "already prepared",
                "prepared_at": existing["prepared_at"]}

    entry = _brain_entry(npi)

    # ── Step 4: capture — open the case at Under Review with the auto-note ──
    add_to_review_queue([{**provider, "_promoted_by": actor}])
    note = _auto_note(provider, entry)
    set_queue_status(npi, "under_review", actor=actor, actor_type="ai",
                     note=f"Auto-prepared: {note}"[:500])

    # ── Step 3: corroborate (network ∥ claim patterns), plus Brain evidence ──
    net_lines, pat_lines = await asyncio.gather(
        _corroborate_network(npi), _corroborate_claim_patterns(npi))
    brain_lines = _corroborate_brain(entry)
    body = "\n".join([
        "AUTO-INVESTIGATION (steps 2-3, machine-gathered — verify before relying on it):",
        f"Lead: {note}",
        "", *brain_lines, "", *net_lines, "", *pat_lines,
    ])[:3900]
    add_case_note(npi, body, actor=actor, actor_type="ai")

    # ── Step 6: validate the referral packet builds, then attach it ──────────
    packet_ok, packet_err = True, ""
    try:
        from services.referral_packet import build_referral_packet
        from services.slim_cache_enricher import enrich_provider_detail
        enriched, _slim = enrich_provider_detail(dict(provider))
        await asyncio.wait_for(
            build_referral_packet(npi, provider=enriched), timeout=PACKET_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        packet_ok, packet_err = False, f"{type(exc).__name__}: {exc}"
        logger.warning("case_prep: packet build failed for %s: %s", npi, packet_err)
    add_document(npi, {
        "type": "referral_packet",
        "title": "Referral packet (auto-prepared)",
        "url": f"/api/providers/{npi}/referral-packet",
        "status": "ready" if packet_ok else f"build failed — open manually ({packet_err[:120]})",
    })

    # ── Hand-off: mark prepared; the human takes it from here ────────────────
    add_case_note(
        npi,
        "CASE PREPARED — ready for your review. Next (human-only): read the referral "
        "packet, decide if it's real (set Confirmed), submit at tips.oig.hhs.gov / the "
        "state MFCU, then mark it Reported. Nothing has been submitted automatically.",
        actor=actor, actor_type="ai")
    mark_prepared(npi, actor=actor)

    return {"ok": True, "npi": npi,
            "provider_name": provider.get("provider_name")
                             or (provider.get("nppes") or {}).get("name") or "",
            "brain_score": (entry or {}).get("brain_score"),
            "packet_ok": packet_ok,
            "elapsed_s": round(time.time() - t0, 1)}


# ── Nightly auto-prepare: ONE lead per day ───────────────────────────────────
# Dave submits at most one referral a day, so the nightly job prepares exactly
# the #1 fresh unworked Brain lead — never a batch. State (last run date, what
# was prepared) is a small JSON persisted to disk + GCS so restarts/redeploys
# can't double-prepare a day or silently skip one.

import datetime as _dt
import json as _json
import pathlib as _pathlib

_STATE_FILE = _pathlib.Path(__file__).parent.parent / "auto_prep_state.json"
AUTO_PREP_HOUR_UTC = 9  # ~2am Pacific / 3am Mountain — after any data refresh


def _load_state() -> dict:
    try:
        return _json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.write_text(_json.dumps(state, indent=2), encoding="utf-8")
    try:
        from core.gcs_sync import upload_file
        upload_file("auto_prep_state.json")
    except Exception:  # noqa: BLE001
        logger.warning("case_prep: GCS upload of auto_prep_state.json failed", exc_info=True)


def get_auto_prep_status() -> dict:
    """For the UI/API: when it last ran and what it prepared."""
    return {"enabled": True, "one_per_day": True,
            "runs_at_utc_hour": AUTO_PREP_HOUR_UTC, **_load_state()}


async def run_auto_prep_once(*, force: bool = False) -> dict:
    """Prepare today's single lead if it hasn't been done yet today."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    state = _load_state()
    if not force and state.get("last_run_date") == today:
        return {"ok": False, "skipped": "already ran today", **state}
    npi = pick_nightly_lead()
    if not npi:
        state.update({"last_run_date": today, "last_result": "nothing to prepare "
                      "(board empty or all top leads already worked/prepared)"})
        _save_state(state)
        return {"ok": False, "skipped": "no eligible lead", **state}
    result = await prepare_case(npi, actor="nightly-auto-prep")
    state.update({
        "last_run_date": today,
        "last_prepared_npi": npi if result.get("ok") else state.get("last_prepared_npi"),
        "last_result": ("prepared " + npi) if result.get("ok")
                       else f"failed: {result.get('error', 'unknown')}",
        "last_run_at": time.time(),
    })
    _save_state(state)
    return {**result, **state}


async def auto_prep_loop() -> None:
    """Background task (started from main.py lifespan): once past the daily
    hour, run the single-lead preparation. Checks every 30 min; the date guard
    in run_auto_prep_once makes restarts and multiple checks harmless."""
    await asyncio.sleep(120)  # let startup (state download, caches) settle
    while True:
        try:
            now = _dt.datetime.now(_dt.timezone.utc)
            if now.hour >= AUTO_PREP_HOUR_UTC:
                res = await run_auto_prep_once()
                if res.get("ok"):
                    logger.info("nightly auto-prep: prepared %s (%s)",
                                res.get("npi"), res.get("provider_name"))
        except Exception:  # noqa: BLE001 — the loop must survive anything
            logger.error("nightly auto-prep iteration failed", exc_info=True)
        await asyncio.sleep(1800)


# queue_status values that mean a human has actually started working the
# case — auto-prepare must not touch these. "open" is deliberately NOT here:
# it's the default the instant a provider is merely added to the queue, before
# any investigation happens, so it stays eligible for auto-preparation.
_ALREADY_WORKED_STATUSES = {"under_review", "tip_filed", "confirmed", "referred", "dismissed", "archived"}


def pick_nightly_lead() -> str | None:
    """The ONE provider the nightly job prepares: the #1 fresh Brain lead that
    isn't already being worked (queue_status beyond 'open') and hasn't been
    auto-prepared yet. Returns None when there's nothing to do (board empty,
    or every top lead is already in progress or prepared)."""
    try:
        from services.fraud_brain import get_top_frauds
        from core.review_store import get_review_item
        board = get_top_frauds(limit=10)
        for e in board.get("top", []):
            if e.get("queue_status") in _ALREADY_WORKED_STATUSES:
                continue
            item = get_review_item(e["npi"])
            if item and item.get("prepared_at"):
                continue
            return e["npi"]
    except Exception:  # noqa: BLE001
        logger.warning("case_prep: nightly lead pick failed", exc_info=True)
    return None
