"""
Per-provider answer sheet for the DOJ Criminal Tip Rewards Pilot Program portal
(america.gov/fraud), plus the DOJ priority-area classifier.

The portal is NOT a fixed wizard like the OIG Hotline. It is a Treasury-run
AI chat intake (america.gov/chat, OMB 1505-0284). Verified 2026-10-20:
  - First box "What raised your concern?" is a textarea with maxLength 2000.
  - Up to 5 attachments, 50MB each; csv doc docx eml json jpeg jpg msg pdf png
    txt webp xls xlsx (NO .html).
  - The AI then asks follow-ups and shows a review card: What happened / Who was
    involved / Amount / Supporting documents / Contact information -> Submit ->
    a reference number and a downloadable copy.
  - It refuses test or hypothetical text, so screens after step 1 can be mapped
    only from a real filing.

Reward rules (DOJ T&C + FAQ, 2026-10-20): $10k-$30k per distinct tip, paid
after charges are unsealed; contact info REQUIRED when filing for yourself
(anonymous only through an attorney); original = independent knowledge or
independent analysis that reveals what is "not generally known".

Like the OIG guide, every answer is derived from THIS provider (taxonomy,
signals, months, entity type, prior filings) — never a fixed checklist.
"""
from __future__ import annotations

import datetime as _dt

PORTAL_URL = "https://america.gov/fraud"
# The portal's first textarea has maxLength=2000. Stay under it with margin so a
# browser that counts line breaks as two characters can't truncate the paste.
DOJ_DESC_CAP = 1950

# DOJ names four priority areas for the pilot: "hospice, home health care, day
# care, and special services fraud". Taxonomy keyword -> area; first match wins.
# "Special services" is DOJ's own undefined term. We read it as the
# disability / special-needs service lines that recent Medicaid fraud cases
# centred on: autism/ABA, developmental- and intellectual-disability waiver
# supports, early intervention, respite, supported living and housing
# stabilization. That reading is a judgment call — keep the keywords narrow so
# a general "behavioral health" clinic is NOT tagged.
_PRIORITY_MAP: list[tuple[tuple[str, ...], str]] = [
    (("hospice",), "Hospice"),
    (("home health", "home care", "home infusion", "personal care", "private duty",
      "homemaker", "in home supportive", "attendant care"), "Home health care"),
    (("child care", "day care", "daycare", "adult day", "day training",
      "day habilitation"), "Day care"),
    (("behavior analyst", "applied behavior", "autism", "developmental disab",
      "intellectual disab", "early intervention", "respite", "supported living",
      "supports brokerage", "housing", "waiver"), "Special services"),
]


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def doj_priority(taxonomies: list[str] | str | None) -> dict:
    """Is this provider in a DOJ priority area? Checks EVERY taxonomy on file —
    a secondary taxonomy can be the material one."""
    if isinstance(taxonomies, str):
        taxonomies = [taxonomies]
    for tax in taxonomies or []:
        t = _norm(tax)
        if not t:
            continue
        for keys, area in _PRIORITY_MAP:
            if any(k in t for k in keys):
                return {"priority": True, "area": area, "taxonomy": tax}
    return {"priority": False, "area": "", "taxonomy": ""}


def prior_filings(npi: str) -> list[dict]:
    """Earlier OIG / MFCU filings for this NPI, oldest first. DOJ counts a tip as
    original if the tipster "was a source of that information" — so the DOJ
    report must SAY Dave filed it before, with the date and agency."""
    out: list[dict] = []
    try:
        from core.oig_tips_store import get_tip_by_npi
        tip = get_tip_by_npi(npi, "oig")
        if tip and tip.get("filed_at"):
            out.append({"agency": "HHS-OIG Hotline", "at": float(tip["filed_at"])})
    except Exception:
        pass
    try:
        from core.referral_workflow import get_referral_by_npi
        for r in get_referral_by_npi(npi) or []:
            when = r.get("referral_date") or r.get("created_at")
            if when:
                juris = (r.get("jurisdiction") or "").strip()
                out.append({"agency": f"{juris + ' ' if juris else ''}state MFCU".strip(),
                            "at": float(when)})
                break
    except Exception:
        pass
    # A ledger status set by hand from the Review Queue leaves no tip/referral
    # record — fall back to the audit trail so the disclosure is never missed.
    try:
        from core.review_store import get_review_item
        item = get_review_item(npi) or {}
        have = {f["agency"].split()[0] for f in out}
        for a in item.get("audit_trail") or []:
            new = a.get("new_queue_status")
            if new == "tip_filed" and "HHS-OIG" not in have:
                out.append({"agency": "HHS-OIG Hotline", "at": float(a.get("timestamp") or 0)})
                have.add("HHS-OIG")
            elif new == "referred" and not any("MFCU" in f["agency"] for f in out):
                out.append({"agency": "state MFCU", "at": float(a.get("timestamp") or 0)})
    except Exception:
        pass
    return sorted(out, key=lambda f: f["at"])


def _fmt_day(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "(date unknown)"


def prior_filing_sentence(filings: list[dict]) -> str:
    if not filings:
        return ""
    parts = [f"{f['agency']} on {_fmt_day(f['at'])}" for f in filings]
    return ("I previously reported this provider to " + " and ".join(parts) +
            "; I am the original source of this analysis.")


def build_doj_filing_guide(*, npi: str, name: str, taxonomies: list[str], state: str,
                           first_month: str | None, last_month: str | None,
                           total_paid: float, address: str, phone: str,
                           entity_type: str | None, flagged_signals: list[str],
                           filings: list[dict], oig_excluded: bool) -> dict:
    pri = doj_priority(taxonomies)
    subject_type = "Individual" if _norm(entity_type) == "npi-1" else "Business"
    period = f"{first_month or '?'} to {last_month or '?'}"
    who = ", ".join(x for x in [name, f"NPI {npi}", address, phone] if x)
    steps = [
        ("Open the portal", f"{PORTAL_URL} -> 'Start your report' -> 'Report fraud' -> Start"),
        ("What raised your concern? (2,000-char box)",
         "Paste the SHORT version (button 'Copy short version'). It already names the "
         "provider, NPI, period, dollars and the top findings."),
        ("Add supporting documents (up to 5, 50MB each)",
         "Attach the FULL narrative as .txt ('Download full narrative'). Optional: the "
         "referral packet printed to PDF. .html is NOT accepted."),
        ("Who was involved?", f"{who} ({subject_type})"),
        ("Which program?", "Medicaid"),
        ("When did it happen?", f"{period} (most recent billed month in the public data: "
                                f"{last_month or '?'}; still occurring: not sure)"),
        ("Amount", f"${total_paid:,.0f} paid by Medicaid over {period} - total exposure, "
                   "NOT a proven loss"),
        ("How do you know?", "My own independent analysis of public HHS T-MSIS Medicaid "
                             "spending data, NPPES, OIG LEIE and SAM.gov. No insider "
                             "knowledge; no other witness."),
        ("Contact information", "Give your real name, email and phone. REQUIRED for a "
                                "reward when you file for yourself (anonymous is only "
                                "allowed through an attorney)."),
        ("After Submit", "Copy the reference number into 'Log as filed', and use "
                         "'Download' to keep the portal's copy."),
    ]
    notes = []
    if pri["priority"]:
        notes.append(f"DOJ PRIORITY AREA: {pri['area']} (taxonomy '{pri['taxonomy']}'). "
                     "DOJ names hospice, home health, day care and special services as "
                     "its priority fraud types for this program.")
    if filings:
        notes.append("Already reported: " + prior_filing_sentence(filings) +
                     " This sentence is in the short version. Keep it: DOJ counts you as "
                     "an original source only if you were the source of the earlier report.")
    if oig_excluded:
        notes.append("Subject is on the OIG LEIE. A bare exclusion match is public "
                     "information. DOJ's originality test wants analysis that reveals "
                     "something 'not generally known', so lead with the billing findings.")
    notes += [
        "Reward: $10,000-$30,000 per distinct tip, at DOJ's discretion, paid only if "
        "the tip leads to unsealed criminal charges. Not guaranteed.",
        "The portal is an AI chat. Its follow-up questions can vary. Answer them from "
        "the lines above and never guess. 'Unknown' is a valid answer.",
    ]
    return {
        "url": PORTAL_URL,
        "steps": steps,
        "notes": notes,
        "priority": pri,
        "prior_filings": [{"agency": f["agency"], "date": _fmt_day(f["at"])} for f in filings],
    }


def render_doj_filing_guide(guide: dict) -> str:
    lines = ["FILING GUIDE - DOJ CRIMINAL TIP REWARDS PORTAL (for you; do NOT paste this section)",
             f"  Portal: {guide['url']}", ""]
    for i, (q, a) in enumerate(guide["steps"], 1):
        lines.append(f"  {i:>2}. {q}")
        lines.append(f"      -> {a}")
    lines += ["", "  Notes:"]
    lines += [f"    - {n}" for n in guide["notes"]]
    lines += ["", "  Everything below the COPY line is the FULL narrative: attach it as a .txt.",
              "", "=" * 30 + " COPY FROM HERE " + "=" * 30, ""]
    return "\n".join(lines)
