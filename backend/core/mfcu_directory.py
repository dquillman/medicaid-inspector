"""
State Medicaid Fraud Control Unit (MFCU) directory.

Every US state (+ DC, PR, VI) has an MFCU, almost always housed in the state
Attorney General's office. This maps a provider's 2-letter state to how to
reach that state's MFCU so the referral flow can auto-target the right one.

HONESTY RULE: we never fabricate a contact URL/phone. Entries in _VERIFIED were
confirmed against the state's own site (or this project's own filing). For every
other state we return the office name (a reliable pattern) plus a direct lookup
link — a Google deep-link and the authoritative national directories — flagged
`verified: false` so the UI tells the analyst to confirm before filing.
"""

# Authoritative national directories (fallback + verification source).
HHS_OIG_DIRECTORY = "https://oig.hhs.gov/fraud/medicaid-fraud-control-units-mfcu/"
NAMFCU_DIRECTORY = "https://www.naag.org/about-naag/namfcu/"

_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico", "VI": "U.S. Virgin Islands",
}

# state code -> {url, phone} confirmed against the unit's own site.
_VERIFIED = {
    "AZ": {"url": "https://www.azag.gov/complaints/mfcu", "phone": "602-542-3881"},
    "CT": {"url": "https://portal.ct.gov/dcj/knowledge-base/articles/specialized-units/medicaid-fraud-control-unit", "phone": ""},
    "HI": {"url": "https://ag.hawaii.gov/cjd/medicaid-fraud-control-unit/", "phone": ""},
    "DE": {"url": "https://attorneygeneral.delaware.gov/fraud/mfcu/", "phone": ""},
    "WV": {"url": "https://ago.wv.gov/medicaid-fraud-control-unit-mfcu", "phone": ""},
    "IN": {"url": "https://www.in.gov/attorneygeneral/about-the-office/medicaid-fraud-and-patient-abuse/medicaid-fraud-resources/", "phone": ""},
    "VA": {"url": "https://www.oag.state.va.us/programs-outreach/medicaid-fraud", "phone": ""},
}


def get_mfcu(state: str) -> dict:
    """Resolve a 2-letter state code to its MFCU. Always returns a dict; a
    `verified` flag tells the caller whether url/phone are confirmed or a
    lookup link the analyst must verify."""
    code = (state or "").strip().upper()
    name = _STATE_NAMES.get(code)
    if not name:
        return {
            "state": code or None, "state_name": None, "office": None,
            "url": None, "phone": None, "verified": False,
            "directory_url": HHS_OIG_DIRECTORY, "namfcu_url": NAMFCU_DIRECTORY,
            "note": "Unknown state — look up the MFCU in the national directory.",
        }
    office = f"{name} Attorney General's Office — Medicaid Fraud Control Unit"
    v = _VERIFIED.get(code)
    if v:
        return {
            "state": code, "state_name": name, "office": office,
            "url": v["url"], "phone": v["phone"], "verified": True,
            "directory_url": HHS_OIG_DIRECTORY, "namfcu_url": NAMFCU_DIRECTORY,
        }
    # Unverified: hand back a reliable lookup link, never a guessed URL.
    q = f"{name} Attorney General Medicaid Fraud Control Unit complaint"
    lookup = "https://www.google.com/search?q=" + q.replace(" ", "+")
    return {
        "state": code, "state_name": name, "office": office,
        "url": lookup, "phone": "", "verified": False,
        "directory_url": HHS_OIG_DIRECTORY, "namfcu_url": NAMFCU_DIRECTORY,
        "note": f"Contact not yet verified — confirm the {name} MFCU's filing page "
                "via this lookup or the national directory before filing.",
    }
