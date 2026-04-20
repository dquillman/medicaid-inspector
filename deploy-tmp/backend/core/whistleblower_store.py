"""
Whistleblower URL store — persists state Medicaid fraud whistleblower links to JSON.
"""
import json
import os
from pathlib import Path
from typing import Dict

_FILE = Path(__file__).resolve().parent.parent / "whistleblower_urls.json"

# Default URLs for every state + DC
_DEFAULTS: Dict[str, Dict[str, str]] = {
    "AL": {"name": "Alabama", "url": "https://medicaid.alabama.gov/content/10.0_Contact/10.3_Fraud_Abuse.aspx"},
    "AK": {"name": "Alaska", "url": "https://health.alaska.gov/dhcs/Pages/fraud.aspx"},
    "AZ": {"name": "Arizona", "url": "https://www.azahcccs.gov/Fraud/"},
    "AR": {"name": "Arkansas", "url": "https://humanservices.arkansas.gov/divisions-shared-services/office-of-inspector-general/report-fraud/"},
    "CA": {"name": "California", "url": "https://oag.ca.gov/mfea/reporting"},
    "CO": {"name": "Colorado", "url": "https://hcpf.colorado.gov/report-fraud-waste-abuse"},
    "CT": {"name": "Connecticut", "url": "https://portal.ct.gov/AG/Medicaid-Fraud/Medicaid-Fraud-Control"},
    "DE": {"name": "Delaware", "url": "https://dhss.delaware.gov/dhss/dmma/fraud.html"},
    "DC": {"name": "District of Columbia", "url": "https://oig.dc.gov/service/report-fraud-waste-or-abuse"},
    "FL": {"name": "Florida", "url": "https://www.myflfamilies.com/services/public-assistance/medicaid/report-medicaid-fraud"},
    "GA": {"name": "Georgia", "url": "https://dch.georgia.gov/report-medicaid-fraud"},
    "HI": {"name": "Hawaii", "url": "https://medquest.hawaii.gov/en/members-applicants/fraud-and-abuse.html"},
    "ID": {"name": "Idaho", "url": "https://healthandwelfare.idaho.gov/providers/fraud-and-abuse/report-fraud-and-abuse"},
    "IL": {"name": "Illinois", "url": "https://hfs.illinois.gov/medicalproviders/fraudbusters.html"},
    "IN": {"name": "Indiana", "url": "https://www.in.gov/medicaid/members/reporting-fraud-and-abuse/"},
    "IA": {"name": "Iowa", "url": "https://dhs.iowa.gov/ime/about/report-fraud"},
    "KS": {"name": "Kansas", "url": "https://www.kancare.ks.gov/consumers/fraud-and-abuse"},
    "KY": {"name": "Kentucky", "url": "https://www.chfs.ky.gov/agencies/oig/Pages/fraud.aspx"},
    "LA": {"name": "Louisiana", "url": "https://ldh.la.gov/page/medicaid-fraud"},
    "ME": {"name": "Maine", "url": "https://www.maine.gov/ag/crime/medicaid_fraud.shtml"},
    "MD": {"name": "Maryland", "url": "https://health.maryland.gov/oig/Pages/Report-Fraud.aspx"},
    "MA": {"name": "Massachusetts", "url": "https://www.mass.gov/how-to/report-masshealth-fraud"},
    "MI": {"name": "Michigan", "url": "https://www.michigan.gov/oig/report-fraud"},
    "MN": {"name": "Minnesota", "url": "https://mn.gov/dhs/general-public/report-fraud/"},
    "MS": {"name": "Mississippi", "url": "https://medicaid.ms.gov/report-fraud/"},
    "MO": {"name": "Missouri", "url": "https://dss.mo.gov/mhd/oversight/fraud.htm"},
    "MT": {"name": "Montana", "url": "https://dphhs.mt.gov/montanahealthcareprograms/fraud"},
    "NE": {"name": "Nebraska", "url": "https://dhhs.ne.gov/Pages/Medicaid-Fraud-and-Abuse.aspx"},
    "NV": {"name": "Nevada", "url": "https://dhcfp.nv.gov/Resources/PI/PIMain/"},
    "NH": {"name": "New Hampshire", "url": "https://www.dhhs.nh.gov/programs-services/medicaid/report-fraud-waste-and-abuse"},
    "NJ": {"name": "New Jersey", "url": "https://www.nj.gov/humanservices/dmahs/info/fraud.html"},
    "NM": {"name": "New Mexico", "url": "https://www.hsd.state.nm.us/providers/fraud-and-abuse/"},
    "NY": {"name": "New York", "url": "https://omig.ny.gov/fraud-reporting"},
    "NC": {"name": "North Carolina", "url": "https://www.ncdoj.gov/protecting-the-public/medicaid-investigations/"},
    "ND": {"name": "North Dakota", "url": "https://www.hhs.nd.gov/healthcare/report-fraud-or-abuse"},
    "OH": {"name": "Ohio", "url": "https://medicaid.ohio.gov/resources/reports-and-research/fraud-and-abuse"},
    "OK": {"name": "Oklahoma", "url": "https://oklahoma.gov/ohca/individuals/report-fraud.html"},
    "OR": {"name": "Oregon", "url": "https://www.oregon.gov/doj/consumer/Pages/medicaid-fraud.aspx"},
    "PA": {"name": "Pennsylvania", "url": "https://www.dhs.pa.gov/providers/Fraud-and-Abuse/Pages/default.aspx"},
    "RI": {"name": "Rhode Island", "url": "https://riag.ri.gov/about-our-office/divisions/medicaid-fraud-control-unit"},
    "SC": {"name": "South Carolina", "url": "https://www.scdhhs.gov/report-fraud"},
    "SD": {"name": "South Dakota", "url": "https://dss.sd.gov/medicaid/generalinfo/fraud.aspx"},
    "TN": {"name": "Tennessee", "url": "https://www.tn.gov/tenncare/fraud-and-abuse.html"},
    "TX": {"name": "Texas", "url": "https://oig.hhs.texas.gov/report-fraud-waste-or-abuse"},
    "UT": {"name": "Utah", "url": "https://medicaid.utah.gov/fraud-abuse/"},
    "VT": {"name": "Vermont", "url": "https://ago.vermont.gov/medicaid-fraud-control-unit"},
    "VA": {"name": "Virginia", "url": "https://www.oag.state.va.us/programs-initiatives/medicaid-fraud-control-unit"},
    "WA": {"name": "Washington", "url": "https://www.hca.wa.gov/about-hca/fraud-and-abuse"},
    "WV": {"name": "West Virginia", "url": "https://dhhr.wv.gov/bms/Pages/Fraud-and-Abuse.aspx"},
    "WI": {"name": "Wisconsin", "url": "https://www.doj.state.wi.us/dci/medicaid-fraud-control-unit"},
    "WY": {"name": "Wyoming", "url": "https://health.wyo.gov/healthcarefin/equalitycare/fraud-abuse/"},
}


def _load() -> Dict[str, Dict[str, str]]:
    if _FILE.exists():
        try:
            with open(_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save(data: Dict[str, Dict[str, str]]) -> None:
    with open(_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_all_urls() -> list:
    """Return merged list: user overrides on top of defaults."""
    overrides = _load()
    result = []
    for code, info in sorted(_DEFAULTS.items(), key=lambda x: x[1]["name"]):
        entry = {"code": code, "name": info["name"], "url": info["url"]}
        if code in overrides:
            entry["url"] = overrides[code]["url"]
            entry["modified"] = True
        result.append(entry)
    return result


def update_url(code: str, url: str) -> dict:
    """Update a single state's whistleblower URL."""
    code = code.upper()
    if code not in _DEFAULTS:
        raise ValueError(f"Unknown state code: {code}")
    overrides = _load()
    overrides[code] = {"url": url}
    _save(overrides)
    return {"code": code, "name": _DEFAULTS[code]["name"], "url": url, "modified": True}


def reset_url(code: str) -> dict:
    """Reset a state back to its default URL."""
    code = code.upper()
    if code not in _DEFAULTS:
        raise ValueError(f"Unknown state code: {code}")
    overrides = _load()
    overrides.pop(code, None)
    _save(overrides)
    return {"code": code, "name": _DEFAULTS[code]["name"], "url": _DEFAULTS[code]["url"]}
