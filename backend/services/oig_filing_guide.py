"""
Per-provider answer sheet for the HHS-OIG Hotline complaint wizard.

Dave's rule (2026-07-25): "Not all of the fields you chose will be the same for
other providers — recommend selections based on the SPECIFIC provider we are
reporting." So nothing here is a fixed checklist: every answer is derived from
that provider's own taxonomy, fired signals, billing dates, entity type, and
case history.

The wizard's screens and exact option strings were verified by walking the live
form at https://tips.oig.hhs.gov on 2026-07-25 (see _OPTIONS below — these are
the form's literal labels, so an answer can be matched by eye without guessing).
"""
from __future__ import annotations

# Literal option strings from the live form — keep in sync if OIG changes them.
_PROGRAM_TYPES = [
    "Hospice", "Home Health", "Durable Medical Equipment",
    "Prescription Drug/ Pharmacy", "Hospitals",
    "Nursing Home/ Extended Care Facility",
    "Doctor/ Ambulance Companies/ Clinics, etc.", "Other",
]
_CATEGORIES = [
    "DME Company", "Home Health Care", "Laboratory", "Marketing Company",
    "Medical Practice/Hospital/Clinic", "Medical Supply Company",
    "Nursing Home/Assisted Living", "Rehabilitation Facility", "Adult Day Care",
    "Ambulance/Medical Transport Service", "Billing Company",
    "Government Contractor", "Government Grantee", "Hospice",
    "Insurance Company", "Mental Health Provider", "Pharmacy",
    "State/Local/Tribal Agency", "Substance Abuse Treatment", "Other Business",
]

_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "VI": "Virgin Islands", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "GU": "Guam",
}

# taxonomy keyword -> (program type, subject category). First match wins, so the
# most specific keywords come first.
_TAXONOMY_MAP: list[tuple[tuple[str, ...], str, str]] = [
    (("hospice",), "Hospice", "Hospice"),
    (("home health", "home care"), "Home Health", "Home Health Care"),
    (("durable medical", "dme", "orthotic", "prosthet", "supplier"),
     "Durable Medical Equipment", "DME Company"),
    (("pharmac", "drug"), "Prescription Drug/ Pharmacy", "Pharmacy"),
    (("hospital",), "Hospitals", "Medical Practice/Hospital/Clinic"),
    (("nursing", "skilled nursing", "assisted living", "custodial care", "long term care"),
     "Nursing Home/ Extended Care Facility", "Nursing Home/Assisted Living"),
    (("substance abuse", "addiction", "chemical dependency", "methadone", "opioid treatment"),
     "Doctor/ Ambulance Companies/ Clinics, etc.", "Substance Abuse Treatment"),
    (("psychiatry", "psycholog", "mental health", "behavioral", "counsel", "social worker"),
     "Doctor/ Ambulance Companies/ Clinics, etc.", "Mental Health Provider"),
    (("ambulance", "transport"),
     "Doctor/ Ambulance Companies/ Clinics, etc.", "Ambulance/Medical Transport Service"),
    (("laborator", "patholog", "clinical lab"),
     "Doctor/ Ambulance Companies/ Clinics, etc.", "Laboratory"),
    (("rehabilitat", "physical therap", "occupational therap", "speech"),
     "Doctor/ Ambulance Companies/ Clinics, etc.", "Rehabilitation Facility"),
    (("adult day",), "Doctor/ Ambulance Companies/ Clinics, etc.", "Adult Day Care"),
]

# fired-signal -> allegation type. Checked in order; the first hit wins.
_ALLEGATION_BY_SIGNAL: list[tuple[tuple[str, ...], str, str]] = [
    (("corporate_shell_risk", "address_cluster_risk"), "Kickbacks",
     "shell/address-cluster signals point at referral arrangements"),
    (("diagnosis_procedure_mismatch", "specialty_mismatch"), "Medically unnecessary services",
     "services billed do not match the diagnosis/specialty"),
]


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def build_filing_guide(*, npi: str, name: str, taxonomy: str, state: str,
                       last_month: str | None, flagged_signals: list[str],
                       entity_type: str | None, previously_reported: bool,
                       address: str) -> dict:
    """Derive every OIG-wizard answer for THIS provider. Returns a dict of
    {step label: answer} plus the notes explaining any judgment call."""
    tax = _norm(taxonomy)

    program_type, category = "Doctor/ Ambulance Companies/ Clinics, etc.", "Medical Practice/Hospital/Clinic"
    for keys, ptype, cat in _TAXONOMY_MAP:
        if any(k in tax for k in keys):
            program_type, category = ptype, cat
            break

    sigs = {_norm(s) for s in (flagged_signals or [])}
    allegation, why = "Improper billing", "billing-volume/intensity anomalies"
    for keys, alleg, reason in _ALLEGATION_BY_SIGNAL:
        if sigs & set(keys):
            allegation, why = alleg, reason
            break

    # Date of activity: the last month the provider billed in the data. The form
    # wants a single date; the 1st of that month is the honest approximation
    # (the dataset is monthly, so a specific day is not knowable).
    if last_month and "-" in str(last_month):
        y, m = str(last_month).split("-")[:2]
        date_answer = f"{m}/01/{y}"
    else:
        date_answer = "(unknown — use the last month shown in the narrative)"

    subject_type = "Individual" if _norm(entity_type) == "npi-1" else "Business"
    state_full = _STATE_NAMES.get((state or "").strip().upper(), state or "")

    return {
        "url": "https://tips.oig.hhs.gov/",
        "steps": [
            ("What is your complaint regarding?", "Healthcare fraud"),
            ("Which fraudulent action are you reporting?", allegation),
            ("Which program does this relate to?", "Medicaid"),
            ("Which type of program does this relate to?", program_type),
            ("When did the activity occur?", date_answer),
            ("Is the activity still occurring?", "Not sure"),
            ("Has this previously been reported to anyone?", "Yes" if previously_reported else "No"),
            ("Are you reporting about a business or an individual?", subject_type),
            ("Subject category", category),
            ("Subject state (use the full name)", state_full),
            ("Is there anyone else that can corroborate?", "No"),
            ("Are you an HHS employee, contractor, or grantee?", "No"),
        ],
        "notes": [
            f"Allegation = '{allegation}' because {why}.",
            f"Program type / category derived from taxonomy '{taxonomy or 'unknown'}'.",
            "'Not sure' on still-occurring: the dataset ends at the last billed month; "
            "activity after that is unknown.",
            "Helpful documents: .html is NOT an accepted extension. Either paste the "
            "evidence list (see the narrative's source section) or attach the referral "
            "packet as a PDF (open it, Ctrl+P, Save as PDF).",
            "Consent to disclose identity: 'Confidential' keeps you contactable for "
            "follow-up while keeping your name inside OIG. Your call each time.",
        ],
        "subject_fields": {
            "Business/Department name": name,
            "National Provider ID (NPI)": npi,
            "Address": address,
            "Category": category,
            "State": state_full,
        },
    }


def render_filing_guide(guide: dict) -> str:
    """Plain-text block for the top of the referral narrative."""
    lines = ["FILING GUIDE - HHS-OIG HOTLINE (for you; do NOT paste this section)",
             f"  Form: {guide['url']}", ""]
    for i, (q, a) in enumerate(guide["steps"], 1):
        lines.append(f"  {i:>2}. {q:<46} -> {a}")
    lines += ["", "  Notes:"]
    lines += [f"    - {n}" for n in guide["notes"]]
    lines += ["", "  Paste everything below the COPY line into "
                  "'Please describe the fraudulent action in your own words'.",
              "", "=" * 30 + " COPY FROM HERE " + "=" * 30, ""]
    return "\n".join(lines)
