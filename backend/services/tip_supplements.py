"""
Update notes for filed tips that left out the per-se key finding.

Before v3.61.3 the referral generator never read the per-se sweep, so tips on
Medicare-revoked, state-terminated and dead-NPI providers listed only the
statistical signals and put total Medicaid paid in the DOJ "Amount" box. The
fact that makes those leads provable, and the amount paid while barred, never
reached the agency. This finds those tips and writes a short update note that
adds the one missing fact. The filer sends it as a follow-up; the original tip
stands.
"""
import datetime

from core import oig_tips_store, perse_store

# v3.61.3 (commit 2ca5592) — tips logged after this came from the generator
# that leads with the KEY FINDING block.
KEY_FINDING_FIX_TS = 1792729841

# Words the old report would have used if it carried the finding. The LEIE
# marker is the old report's own "** FEDERAL EXCLUSION:" line; its all-clear
# line reads "Federal exclusion check:", so the colon tells them apart.
_FINDING_WORDS = {
    "active_exclusion": ("federal exclusion:", "exclusion list (leie, excluded"),
    "medicare_revoked_billing": ("revoked",),
    "paid_while_terminated": ("terminated this provider", "enrollment for cause"),
    "deactivated_billing": ("deactivated",),
    "deactivated_window": ("deactivated",),
}

_SOURCE = {
    "active_exclusion": "the HHS-OIG exclusion list (LEIE)",
    "medicare_revoked_billing": "the CMS Medicare revocation list",
    "paid_while_terminated": "HHS Medicaid provider enrollment data",
    "deactivated_billing": "NPPES (the national NPI registry)",
    "deactivated_window": "NPPES (the national NPI registry)",
}

METHODS_URL = "https://medicaid-inspector.web.app/methods"
DOJ_BOX_CAP = 2000


def _date(ts: float) -> str:
    return datetime.date.fromtimestamp(ts).isoformat()


def _coverage(tip: dict, kind: str) -> str:
    """'missing' — saved text checked and the finding is not in it;
    'likely_missing' — no text saved, logged before the fix;
    'covered' — the finding is already in the tip (or was sent as an update)."""
    if tip.get("supplements"):
        return "covered"
    text = (tip.get("filed_text") or "").lower()
    if text:
        if "key finding" in text or any(w in text for w in _FINDING_WORDS[kind]):
            return "covered"
        return "missing"
    if tip.get("filed_at", 0) >= KEY_FINDING_FIX_TS:
        return "covered"
    # The old report always printed the LEIE hit; only the barred amount was lost.
    if kind == "active_exclusion":
        return "covered"
    return "likely_missing"


def build_note(tip: dict, lead: dict, finding: dict) -> str:
    dest = tip.get("destination") or "oig"
    ref = tip.get("reference_number") or ""
    when = _date(tip.get("filed_at", 0))
    if dest == "doj":
        opener = f"UPDATE TO MY EARLIER TIP - reference {ref}, filed {when} at america.gov/fraud."
    else:
        opener = (f"UPDATE TO MY HHS-OIG HOTLINE COMPLAINT filed {when} "
                  f"(my own reference {ref}; the Hotline issues no number).")
    name = tip.get("provider_name") or lead.get("provider_name") or "the provider"
    state = lead.get("state") or tip.get("state") or ""
    lines = [
        opener,
        "",
        f"Provider: {name}, NPI {tip['npi']}" + (f", {state}." if state else "."),
        "",
        "My first report left out its most important fact. I am adding it now.",
        "",
        "KEY FINDING: " + finding["headline"],
        "",
        f"Amount Medicaid paid while barred: ${finding['amount']:,.0f} ({finding['amount_label']}). "
        f"Total Medicaid paid in the public data: ${finding['total_paid']:,.0f}.",
    ]
    if finding.get("citation"):
        lines.append(f"Legal basis: {finding['citation']}.")
    if finding.get("caveat"):
        lines.append(f"Note: {finding['caveat']}")
    lines += [
        "",
        f"Source: my own analysis of public data - {_SOURCE[lead['kind']]} matched by NPI "
        f"to CMS T-MSIS Medicaid payments. Methods: {METHODS_URL}",
        "Everything else in my first report stands. I filed it and I am the same person.",
    ]
    text = "\n".join(lines)
    return text[:DOJ_BOX_CAP] if dest == "doj" else text


def find_supplements() -> dict:
    """Every filed tip whose per-se finding never reached the agency."""
    items, skipped = [], []
    for tip in oig_tips_store.list_tips():
        lead = perse_store.get_lead(tip.get("npi", ""))
        kind = (lead or {}).get("kind")
        if kind not in _FINDING_WORDS:
            continue  # no per-se lead, or a recovery lead (no billing while barred)
        finding = perse_store.describe_finding(lead)
        if not finding or finding["amount"] <= 0:
            continue
        coverage = _coverage(tip, kind)
        if coverage == "covered":
            continue
        base = {
            "tip_id": tip["id"], "npi": tip["npi"],
            "destination": tip.get("destination") or "oig",
            "provider_name": tip.get("provider_name") or "",
            "reference_number": tip.get("reference_number") or "",
            "filed_at": tip.get("filed_at"), "kind": kind,
        }
        if lead.get("weak"):
            # A short NPI gap is usually paperwork; sending it as the key fact
            # would weaken the tip, not strengthen it.
            skipped.append({**base, "reason": (
                f"NPI gap of only {lead.get('gap_days')} days - most likely paperwork, "
                "not a provable bar. No update recommended.")})
            continue
        items.append({
            **base, "coverage": coverage,
            "headline": finding["headline"], "amount": finding["amount"],
            "amount_label": finding["amount_label"],
            "text": build_note(tip, lead, finding),
        })
    items.sort(key=lambda i: -i["amount"])
    return {"items": items, "skipped": skipped}
