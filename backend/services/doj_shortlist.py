"""
DOJ shortlist: the leads most likely to earn a Criminal Tip Rewards award,
ordered by how provable they are.

DOJ pays only when a tip leads to unsealed criminal charges, so the order is:

  tier 1  Worked cases: confirmed fraud, or already reported to OIG / an MFCU,
          and not yet sent to DOJ. A human has already judged these.
  tier 2  Per-se findings: billing while OIG-excluded, after a Medicare
          revocation, or under a deactivated NPI. Facts a prosecutor can check
          in minutes. Recovery leads (all billing BEFORE the exclusion) are left
          out: nothing was billed while barred.
  tier 3  Statistical Brain leads in DOJ's priority areas (hospice, home
          health, day care, special services).

Inside a tier, DOJ priority areas come first, then the dollar figure.

Filters that apply to every tier:
  * Leads already logged with DOJ (any NPI of the same company), dismissed
    (judged not fraud) or archived are dropped.
  * One company billing under several NPIs is one row (DOJ pays per distinct
    tip); the other NPIs are listed on it.
  * The general federal limitation period is 5 years (18 U.S.C. 3282), so a
    lead whose most recent billing is older than that is dropped. DOJ decides
    timeliness; this keeps clearly stale leads off the list.

NOTE on the other age cutoff in this codebase (audit 2026-10-24, item 11):
services/fraud_brain.py's recency_badge() marks a provider "expired" at ~6
years, based on the FCA CIVIL recovery window, not this file's 5-year
CRIMINAL statute of limitations — they are deliberately different numbers
for different legal bases, not an inconsistency. Both are reversible
prioritization filters, not a legal eligibility determination: the Fraud
Brain board still shows expired/stale leads with a badge rather than hiding
them, and routes/review.py's queue auto-backfill is the only place recency
silently skips a candidate (for picking NEW queue slots, not for search).
"""
from __future__ import annotations

import datetime as _dt
import re

LIMITATION_YEARS = 5

# deactivated_window (NPI deactivated, then reactivated) needs a long gap.
# Most gaps are paperwork lapses (median 40 days, measured 2026-10-21; Seven
# Hills RI alone had six NPIs on the list), and a lapse the provider fixed
# within weeks will not support criminal charges. A gap of six months or more
# is not a lapse (Great Bay Services: ~3 years), so those stay. Short-gap
# leads remain on the Excluded page.
MIN_WINDOW_GAP_DAYS = 180
_PERSE_KIND_ORDER = {
    "active_exclusion": 0,
    "medicare_revoked_billing": 1,
    "paid_while_terminated": 2,
    "deactivated_billing": 3,
    "deactivated_window": 4,
}
_PERSE_REASON = {
    "active_exclusion": "Billed Medicaid while on the OIG exclusion list",
    "medicare_revoked_billing": "Billed Medicaid after Medicare revoked the provider",
    "paid_while_terminated": "Paid by Medicaid after the state terminated its enrollment for cause",
    "deactivated_billing": "Billed Medicaid under a deactivated NPI",
    "deactivated_window": "Billed Medicaid while the NPI was deactivated",
}


def _gap_days(lead: dict) -> int | None:
    try:
        a = _dt.datetime.strptime(lead["deactivation_date"], "%m/%d/%Y")
        b = _dt.datetime.strptime(lead["reactivation_date"], "%m/%d/%Y")
        return (b - a).days
    except (KeyError, TypeError, ValueError):
        return None
_NAME_NOISE = re.compile(r"\b(INC|INCORPORATED|LLC|L\s?L\s?C|LC|PC|P\s?C|PA|PLLC|CORP|CORPORATION|"
                         r"CO|COMPANY|LTD|THE)\b")


def company_key(name: str | None) -> str:
    """One key per company, so a provider billing under several NPIs is one tip."""
    n = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
    return " ".join(_NAME_NOISE.sub(" ", n).split())
_WORKED_REASON = {
    "confirmed": "You confirmed this as fraud",
    "tip_filed": "You reported this to HHS-OIG",
    "referred": "You referred this to the state MFCU",
}
_DROP_STATUSES = {"doj_filed", "dismissed", "archived"}


def _ym_int(s: str | None) -> int | None:
    s = (s or "").strip().replace("-", "")
    return int(s[:6]) if len(s) >= 6 and s[:6].isdigit() else None


def cutoff_month(today: _dt.date | None = None) -> int:
    """First YYYYMM still inside the limitation period."""
    today = today or _dt.date.today()
    return (today.year - LIMITATION_YEARS) * 100 + today.month


def build_shortlist(today: _dt.date | None = None) -> dict:
    from core import perse_store
    from core.oig_tips_store import filed_npis, list_tips
    from core.review_store import get_queue_statuses, get_review_queue
    from core.store import get_provider_by_npi
    from services.doj_filing_guide import doj_priority
    from services.fraud_brain import get_top_frauds

    cutoff = cutoff_month(today)
    doj_filed = filed_npis("doj")
    seen: set[str] = set()
    rows: list[dict] = []
    dropped = {"too_old": 0, "already_doj": 0, "closed": 0, "same_company": 0, "short_lapse": 0}

    def _provider(npi: str) -> dict:
        return get_provider_by_npi(npi) or {}

    def _add(tier: int, npi: str, base: dict, reason: str, amount: float,
             amount_label: str, last_month: str | None, statuses: dict,
             extra: dict | None = None) -> None:
        if npi in seen:
            return
        status = statuses.get(npi)
        if npi in doj_filed or status == "doj_filed":
            dropped["already_doj"] += 1
            return
        if status in _DROP_STATUSES:
            dropped["closed"] += 1
            return
        lm = _ym_int(last_month)
        if lm is None or lm < cutoff:
            dropped["too_old"] += 1
            return
        p = _provider(npi)
        specialty = base.get("specialty") or p.get("specialty") or ""
        seen.add(npi)
        rows.append({
            "npi": npi,
            "tier": tier,
            "provider_name": base.get("provider_name") or p.get("provider_name")
                             or (p.get("nppes") or {}).get("name", ""),
            "state": base.get("state") or p.get("state") or "",
            "specialty": specialty,
            "reason": reason,
            "amount": round(float(amount or 0), 2),
            "amount_label": amount_label,
            "last_month": last_month,
            "doj_priority_area": doj_priority(specialty)["area"] or None,
            "queue_status": status,
            "risk_score": round(float(base.get("risk_score") or p.get("risk_score") or 0), 1),
            "caveat": base.get("caveat") or "",
            **(extra or {}),
        })

    # Tier 1: worked cases not yet sent to DOJ.
    worked = [i for i in get_review_queue() if i.get("queue_status") in _WORKED_REASON]
    statuses = get_queue_statuses([i["npi"] for i in worked])
    for item in worked:
        npi = item["npi"]
        p = _provider(npi)
        _add(1, npi, {**item, "specialty": p.get("specialty")},
             _WORKED_REASON[item["queue_status"]],
             item.get("total_paid") or p.get("total_paid") or 0, "Total Medicaid paid",
             p.get("last_month"), statuses)

    # Tier 2: per-se findings.
    perse = []
    for r in perse_store.list_leads(limit=100_000)["leads"]:
        if r.get("kind") not in _PERSE_KIND_ORDER:
            continue
        if r["kind"] == "deactivated_window":
            gap = r.get("gap_days") if r.get("gap_days") is not None else _gap_days(r)
            if r.get("weak") or gap is None or gap < MIN_WINDOW_GAP_DAYS:
                dropped["short_lapse"] += 1
                continue
            r = {**r, "caveat": (f"The NPI was deactivated for about {gap // 30} months, then "
                                 "reactivated. Check that the state did not keep the provider "
                                 "enrolled under another ID before filing.")}
        perse.append(r)
    statuses = get_queue_statuses([r["npi"] for r in perse])
    for r in perse:
        barred = (r.get("paid_after_exclusion") or r.get("paid_after_revocation")
                  or r.get("paid_while_terminated")
                  or r.get("paid_after_deactivation") or r.get("paid_during_deactivation") or 0)
        _add(2, r["npi"], r, _PERSE_REASON[r["kind"]], barred, "Paid while barred",
             r.get("last_month"), statuses, {"kind": r["kind"]})

    # Tier 3: statistical Brain leads in DOJ priority areas.
    brain = get_top_frauds(25, False, True).get("top", [])
    statuses = get_queue_statuses([e["npi"] for e in brain])
    for e in brain:
        _add(3, e["npi"], e, f"Fraud Brain rank #{e.get('brain_rank', '?')} "
             f"(score {e.get('brain_score', 0):.0f})",
             e.get("total_paid") or 0, "Total Medicaid paid",
             e.get("last_active_month"), statuses, {"brain_rank": e.get("brain_rank")})

    def _key(r: dict):
        return (r["tier"], r["doj_priority_area"] is None,
                _PERSE_KIND_ORDER.get(r.get("kind", ""), 0),
                r.get("brain_rank") or 0, -r["amount"])

    rows.sort(key=_key)

    # A company already filed with DOJ under one NPI is filed under all of them.
    doj_companies = {company_key(t.get("provider_name")) for t in list_tips()
                     if (t.get("destination") or "oig") == "doj"} - {""}
    kept = []
    for r in rows:
        if company_key(r["provider_name"]) in doj_companies:
            dropped["already_doj"] += 1
        else:
            kept.append(r)
    rows = kept

    # DOJ pays one award per DISTINCT tip, and filing the same company six
    # times under six NPIs reads as spam. Keep the best-ranked row per company
    # and list the others on it.
    merged: list[dict] = []
    by_company: dict[str, dict] = {}
    for r in rows:
        key = company_key(r["provider_name"])
        head = by_company.get(key) if key else None
        if head is None:
            r["related_npis"] = []
            merged.append(r)
            if key:
                by_company[key] = r
            continue
        head["related_npis"].append(r["npi"])
        if r["amount_label"] == head["amount_label"]:
            head["amount"] = round(head["amount"] + r["amount"], 2)
        dropped["same_company"] += 1
    rows = merged
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    by_tier = {t: sum(1 for r in rows if r["tier"] == t) for t in (1, 2, 3)}
    return {
        "leads": rows,
        "total": len(rows),
        "by_tier": by_tier,
        "dropped": dropped,
        "cutoff_month": f"{cutoff // 100:04d}-{cutoff % 100:02d}",
        "limitation_years": LIMITATION_YEARS,
    }
