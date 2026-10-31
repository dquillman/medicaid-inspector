"""
DOJ research shortlist, ordered by existing workflow tiers.

Worked cases and administrative-status discrepancies remain screening leads.
Neither filing nor Medicare revocation establishes Medicaid fraud. Money fields
are payment totals, not established overpayment or recovery. The default
six-year age preference is reversible with include_older=True; unknown periods
remain visible. Timeliness and referral suitability require individual review.
"""
from __future__ import annotations

import datetime as _dt
import re

from core import lead_quality

# v3.63.0: 6 years, the OIG civil money penalty window (42 USC 1320a-7a(c)(1)).
# It was 5, which silently dropped We Care Transportation (excluded 2010, paid
# $4.44M in 2018-2020). Older per-se EXCLUSION cases are no longer dropped at
# all: the False Claims Act can reach back up to 10 years (31 USC 3731(b)), so
# they stay on the list, flagged for a lawyer.
LIMITATION_YEARS = 6
KEEP_OLDER_KINDS = ("active_exclusion", "excluded_servicing")
OLDER_CAVEAT = ("Older than 6 years: only the False Claims Act's up-to-10-year rule may still "
                "apply. Flag it; a lawyer decides.")

# deactivated_window (NPI deactivated, then reactivated) needs a long gap.
# Most gaps are paperwork lapses (median 40 days, measured 2026-10-21; Seven
# Hills RI alone had six NPIs on the list), and a lapse the provider fixed
# within weeks will not support criminal charges. A gap of six months or more
# is not a lapse (Great Bay Services: ~3 years), so those stay. Short-gap
# leads remain on the Excluded page.
MIN_WINDOW_GAP_DAYS = 180
_PERSE_KIND_ORDER = {
    "active_exclusion": 0,
    "excluded_servicing": 1,
    "medicare_revoked_billing": 2,
    "paid_while_terminated": 3,
    "deactivated_billing": 4,
    "deactivated_window": 5,
}
# What the dollar figure actually counts. Different kinds count different
# months, and a reader comparing them needs to know (audit 2026-10-28).
_AMOUNT_LABEL = {
    "active_exclusion": "Payments in whole months after the exclusion date",
    "excluded_servicing": "Payments to other billers for this provider's services, whole months after the exclusion",
    "medicare_revoked_billing": "Payments from 2 months after the Medicare revocation (state grace period)",
    "paid_while_terminated": "Payments in whole months with no active enrollment in any state",
    "deactivated_billing": "Payments in whole months after the NPI was deactivated",
    "deactivated_window": "Payments in whole months inside the deactivation gap",
}
_PERSE_REASON = {
    "active_exclusion": "Billed Medicaid while on the OIG exclusion list",
    "excluded_servicing": "An excluded person provided or ordered services billed by another provider",
    "medicare_revoked_billing": "Billed Medicaid after Medicare revoked the provider",
    "paid_while_terminated": "Paid by Medicaid after the state terminated its enrollment for cause",
    "deactivated_billing": "Billed Medicaid under a deactivated NPI",
    "deactivated_window": "Billed Medicaid while the NPI was deactivated",
}


def _has_federal_record(npi: str) -> bool | None:
    """OIG exclusion or Medicare revocation on file for this NPI. None if neither list is loaded."""
    from core import oig_store, revocation_store
    if not oig_store.get_oig_stats().get("loaded"):
        return None
    return bool(oig_store.is_excluded(npi)[0] or revocation_store.is_revoked(npi))


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
    "confirmed": "Analyst marked confirmed; verify supporting evidence",
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


def build_shortlist(today: _dt.date | None = None, *, include_older: bool = False) -> dict:
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
    dropped = {"too_old": 0, "already_doj": 0, "closed": 0, "same_company": 0, "short_lapse": 0,
               "unreliable_status": 0}

    def _provider(npi: str) -> dict:
        return get_provider_by_npi(npi) or {}

    def _add(tier: int, npi: str, base: dict, reason: str, amount: float,
             amount_label: str, last_month: str | None, statuses: dict,
             extra: dict | None = None, keep_older: bool = False) -> None:
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
        older = lm is not None and lm < cutoff
        if not include_older and older and not keep_older:
            dropped["too_old"] += 1
            return
        caveat = base.get("caveat") or ""
        if older and keep_older:
            caveat = (caveat + " " + OLDER_CAVEAT).strip()
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
            "timeliness_review_required": lm is None or lm < cutoff,
            "timeliness_status": "unknown_period" if lm is None else "older_evidence" if lm < cutoff else "within_priority_window",
            "doj_priority_area": doj_priority(specialty)["area"] or None,
            "queue_status": status,
            "risk_score": round(float(base.get("risk_score") or p.get("risk_score") or 0), 1),
            "caveat": caveat,
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
    blind_states = perse_store.blind_states()
    for r in perse_store.list_leads(limit=100_000)["leads"]:
        if r.get("kind") not in _PERSE_KIND_ORDER:
            continue
        # Audit 2026-10-28: reversed terminations and state mismatches were the
        # biggest false leads in the top list. Dropped here, kept on /excluded.
        if lead_quality.quality_flags(r, blind_states, _has_federal_record(r["npi"])):
            dropped["unreliable_status"] += 1
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
        barred = (r.get("paid_after_exclusion") or r.get("paid_as_servicing_after_exclusion")
                  or r.get("paid_after_revocation")
                  or r.get("paid_while_terminated")
                  or r.get("paid_after_deactivation") or r.get("paid_during_deactivation") or 0)
        _add(2, r["npi"], r, _PERSE_REASON[r["kind"]], barred, _AMOUNT_LABEL[r["kind"]],
             r.get("last_month"), statuses, {"kind": r["kind"],
                 "evidence_class": "administrative_status_lead",
                 "independent_corroboration_required": True,
                 "program_scope_note": ("Medicare status does not establish Medicaid ineligibility; verify applicable Medicaid enrollment and effective dates."
                                        if r["kind"] == "medicare_revoked_billing" else
                                        "Verify identity, effective dates, billing period, and applicable program eligibility before asserting a violation.")},
             keep_older=r["kind"] in KEEP_OLDER_KINDS)

    # Tier 3: statistical Brain leads in DOJ priority areas.
    brain = get_top_frauds(25, False, True).get("top", [])
    statuses = get_queue_statuses([e["npi"] for e in brain])
    for e in brain:
        _add(3, e["npi"], e, f"Fraud Brain rank #{e.get('brain_rank', '?')} "
             f"(score {e.get('brain_score', 0):.0f})",
             e.get("total_paid") or 0, "Total Medicaid paid",
             e.get("last_active_month"), statuses, {"brain_rank": e.get("brain_rank")})

    def _key(r: dict):
        # Inside the 6-year window first; older exclusion cases follow (v3.63.0).
        return (r["tier"], r["timeliness_status"] == "older_evidence", r["doj_priority_area"] is None,
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
        "age_filter": {"include_older": include_older, "reversible": True,
                       "note": "Age is a prioritization filter, not a legal eligibility determination. Unknown periods require review."},
    }
