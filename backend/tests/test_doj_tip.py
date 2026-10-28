"""
DOJ Criminal Tip Rewards destination for the ONE referral-narrative generator.

Rule under test (feedback_reports_are_referral_narratives): the evidence body is
IDENTICAL across destinations; only the routing header/footer, the short
first-box version, the per-field answers and the filing guide differ.
"""
import pytest

from core.review_store import (
    add_to_review_queue, set_queue_status, get_queue_status, QueueStatusError,
    HUMAN_GATED_QUEUE_STATUSES, REPORTED_QUEUE_STATUSES,
)
from services.doj_filing_guide import doj_priority, DOJ_DESC_CAP
from tests.conftest import SAMPLE_PROVIDERS

NPI = "1234567890"


@pytest.fixture(autouse=True)
def _no_live_nppes(monkeypatch):
    async def _none(npi):
        return {}
    import data.nppes_client as nc
    monkeypatch.setattr(nc, "get_provider", _none)


@pytest.fixture
def queued():
    add_to_review_queue([p for p in SAMPLE_PROVIDERS if p["npi"] == NPI])
    yield
    set_queue_status(NPI, "open", actor="test", actor_type="user")


def _tip(client, headers, dest):
    r = client.get(f"/api/providers/{NPI}/oig-tip?destination={dest}&save_note=false", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _evidence_body(text: str) -> str:
    start = text.index("SUBJECT OF COMPLAINT")
    end = text.index("No protected health information")
    return text[start:end]


def test_doj_evidence_body_identical_to_oig(client, auth_headers):
    oig = _tip(client, auth_headers, "oig")
    doj = _tip(client, auth_headers, "doj")
    assert _evidence_body(doj["text"]) == _evidence_body(oig["text"])
    assert doj["text"] != oig["text"]
    assert doj["text"].startswith("DOJ CRIMINAL TIP REWARDS PILOT PROGRAM")
    assert "america.gov/fraud" in doj["text"]
    assert "unsealed criminal charges" in doj["text"]
    assert "FOIA" not in doj["text"]          # the OIG-only footer must not leak in
    assert doj["text"].isascii()


def test_doj_short_version_fits_portal_box_and_names_subject(client, auth_headers):
    doj = _tip(client, auth_headers, "doj")
    short = doj["short_narrative"]
    assert len(short) <= DOJ_DESC_CAP < 2000
    assert NPI in short and "Test Provider A" in short
    assert "independent analysis" in short
    first = doj["form_fields"][0]
    assert first["value"] == short and first["chars"] == len(short)
    # The "How do you know?" card's words are pasted with the first box too.
    how = next(f for f in doj["form_fields"] if f["label"] == "How do you know?")
    assert how["value"] in short


def test_doj_filing_guide_rendered_above_copy_line(client, auth_headers):
    doj = _tip(client, auth_headers, "doj")
    g = doj["filing_guide"]
    assert g and g["url"] == "https://america.gov/fraud"
    assert any("Contact information" in s[0] for s in g["steps"])
    # Live portal (2026-10-21): no Medicaid choice; "Healthcare Fraud" is the pick.
    assert any("Complaint type" in s[0] and "Healthcare Fraud" in s[1] for s in g["steps"])
    guide_part, _, body = doj["text_with_guide"].partition("COPY FROM HERE")
    assert "DOJ CRIMINAL TIP REWARDS PORTAL" in guide_part
    assert body.strip().startswith("=")  # the rest of the separator line
    assert "doj_priority" in doj


def test_doj_discloses_prior_oig_filing(client, auth_headers, queued):
    set_queue_status(NPI, "tip_filed", actor="test", actor_type="user")
    doj = _tip(client, auth_headers, "doj")
    assert "previously reported" in doj["short_narrative"].lower()
    assert "HHS-OIG" in doj["short_narrative"]
    prior = next(f for f in doj["form_fields"] if f["label"] == "Previously reported")
    assert prior["value"] in doj["short_narrative"]
    assert doj["filing_guide"]["prior_filings"]


def test_invalid_destination_still_400(client, auth_headers):
    r = client.get(f"/api/providers/{NPI}/oig-tip?destination=fbi&save_note=false", headers=auth_headers)
    assert r.status_code == 400


def test_doj_filed_is_human_gated_reported_status(queued):
    assert "doj_filed" in REPORTED_QUEUE_STATUSES
    assert "doj_filed" in HUMAN_GATED_QUEUE_STATUSES
    with pytest.raises(QueueStatusError):
        set_queue_status(NPI, "doj_filed", actor="hal", actor_type="ai")
    set_queue_status(NPI, "doj_filed", actor="dave", actor_type="user")
    assert get_queue_status(NPI) == "doj_filed"


def test_log_doj_tip_sets_reported_doj(client, auth_headers, queued):
    r = client.post("/api/oig-tips", headers=auth_headers, json={
        "npi": NPI, "provider_name": "Test Provider A", "destination": "doj",
        "reference_number": "FRAUD-2026-TEST"})
    assert r.status_code == 200, r.text
    tip = r.json()
    assert tip["destination"] == "doj"
    assert tip["reference_number"] == "FRAUD-2026-TEST"
    assert "foia_eligible_at" not in tip
    assert get_queue_status(NPI) == "doj_filed"
    filed = client.get("/api/oig-tips/filed", headers=auth_headers).json()
    assert NPI in filed["doj_npis"]


def test_log_tip_rejects_unknown_destination(client, auth_headers):
    r = client.post("/api/oig-tips", headers=auth_headers, json={"npi": NPI, "destination": "fbi"})
    assert r.status_code == 400


@pytest.mark.parametrize("taxonomies,area", [
    (["Hospice Care, Community Based"], "Hospice"),
    (["Home Health"], "Home health care"),
    (["Personal Care Attendant"], "Home health care"),
    (["Child Day Care"], "Day care"),
    (["Adult Day Care"], "Day care"),
    (["Behavior Analyst"], "Special services"),
    (["Behavior Technician"], "Special services"),
    (["Psychiatry Physician", "Early Intervention Provider Agency"], "Special services"),
])
def test_doj_priority_areas(taxonomies, area):
    p = doj_priority(taxonomies)
    assert p["priority"] and p["area"] == area


@pytest.mark.parametrize("taxonomies", [
    ["Psychiatry Physician"], ["Behavioral Health & Social Service Providers"],
    ["Internal Medicine Physician"], [], None,
])
def test_doj_priority_negative(taxonomies):
    assert doj_priority(taxonomies)["priority"] is False


def test_provider_details_answer_for_the_chat_followup():
    """The DOJ chat asks to 'confirm or clarify details about the provider,
    facility, care setting, program or service ... include the NPI'."""
    from services.doj_filing_guide import provider_details_answer
    a = provider_details_answer(
        npi="1922018118", name="TEXAS BEST CARE HOME HEALTH, INC.",
        address="123 MAIN ST, HOUSTON, TX, 77001", phone="713-555-0100",
        taxonomies=["Home Health Agency", "", "Home Health Agency"], state="TX",
        entity_type="NPI-2", top_code="G0156", top_code_desc="Home health aide services",
    )
    assert "NPI 1922018118" in a
    assert "Texas Medicaid" in a
    assert "Provider type: Home Health Agency." in a        # de-duplicated
    assert "Main service billed: G0156 (Home health aide services)." in a
    assert "(business)" in a
    # Nothing invented when a field is missing.
    b = provider_details_answer(npi="1000000001", name="X", address="", phone="",
                                taxonomies=[], state="", entity_type="NPI-1")
    assert "Location" not in b and "Phone" not in b and "Program: Medicaid" in b


def test_patient_risk_answer_claims_no_harm_it_cannot_know():
    from services.doj_filing_guide import patient_risk_answer
    a = patient_risk_answer(patients=3396, period="2021-12 to 2023-04",
                            taxonomies=["Home Health Agency"])
    assert a.startswith("I have no direct knowledge of harm")
    assert "3,396 patients, often elderly or disabled" in a
    assert "2021-12 to 2023-04" in a


def test_doj_tip_offers_the_chat_followup_answers(client, auth_headers):
    r = client.get(f"/api/providers/{NPI}/oig-tip?destination=doj&save_note=false", headers=auth_headers)
    assert r.status_code == 200
    rows = {f["label"]: f["value"] for f in r.json()["form_fields"]}
    assert f"NPI {NPI}" in rows["Provider details (with NPI)"]
    assert rows["Risk to patients"].startswith("I have no direct knowledge of harm")
    steps = [s[0] for s in r.json()["filing_guide"]["steps"]]
    assert any("Include the NPI" in s for s in steps)
    assert any("risk to patients" in s for s in steps)


_REVOKED_LEAD = {
    "npi": "1669892584", "kind": "medicare_revoked_billing",
    "provider_name": "SOFT TOUCH HOSPICE INC", "state": "CA",
    "specialty": "PART A PROVIDER - HOSPICE", "total_paid": 1_256_153.0,
    "total_claims": 900, "total_beneficiaries": 80,
    "first_month": "2023-09", "last_month": "2024-10",
    "revocation_date": "2023-07-01", "revocation_reason": "424.535(A)(9) Failure To Report",
    "paid_after_revocation": 127_400.0,
    "citation": "42 CFR § 455.416(c) (state Medicaid must terminate a provider Medicare has revoked)",
    "caveat": "",
}


def test_describe_finding_names_the_barred_amount():
    from core.perse_store import describe_finding
    f = describe_finding(_REVOKED_LEAD)
    assert f["amount"] == 127_400.0
    assert "Medicare revoked this provider's enrollment effective 2023-07-01" in f["headline"]
    assert "$127,400" in f["headline"]
    assert describe_finding(None) is None


def test_tip_for_a_per_se_lead_below_the_scan_cutoff(client, auth_headers, monkeypatch):
    """A revoked provider under the $1M scan cutoff used to 404 ('not in scan
    cache'), and when it did draft, the report never mentioned the revocation
    and the DOJ chat picked up total paid ($1.26M) instead of $127K barred."""
    import core.perse_store as perse
    import data.nppes_client as nppes

    async def _no_live(*_a, **_k):
        return {}
    monkeypatch.setattr(nppes, "get_provider", _no_live)
    monkeypatch.setattr(perse, "get_lead",
                        lambda npi: dict(_REVOKED_LEAD) if npi == _REVOKED_LEAD["npi"] else None)

    r = client.get(f"/api/providers/{_REVOKED_LEAD['npi']}/oig-tip?destination=doj&save_note=false",
                   headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "KEY FINDING" in body["text"]
    assert "Medicare revoked" in body["short_narrative"]
    # The first dollar figure the DOJ chat sees is the barred amount.
    assert body["short_narrative"].index("$127,400") < body["short_narrative"].index("$1,256,153")
    rows = {f["label"]: f["value"] for f in body["form_fields"]}
    assert rows["Payments during questioned period"].startswith("$127,400 paid after Medicare revoked")
    assert "composite risk score of 0/100" not in body["text"]


def test_doj_filing_keeps_the_text_as_filed(client, auth_headers, tmp_path, monkeypatch):
    """Most DOJ-shortlist leads have no case to hold a case note, so the filing
    record is where the submitted text lives."""
    import core.oig_tips_store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "oig_tips.json")
    monkeypatch.setattr(store, "_tips", [])
    monkeypatch.setattr(store, "_loaded", True)
    monkeypatch.setattr(store, "_save", lambda: None)
    r = client.post("/api/oig-tips", headers=auth_headers, json={
        "npi": "1999999991", "destination": "doj", "reference_number": "REF-1",
        "filed_text": "SHORT VERSION (first box):\nx\n\nFULL NARRATIVE (attached .txt):\ny",
    })
    assert r.status_code == 200
    assert r.json()["filed_text"].startswith("SHORT VERSION")
    assert r.json()["reference_number"] == "REF-1"


def test_brain_doj_view_serves_priority_rows_with_main_board_rank(monkeypatch):
    """The DOJ view filters the SAME ranking; it never re-scores or re-ranks,
    and a lead already reported to DOJ drops off it like any reported case."""
    import services.fraud_brain as fb
    import core.review_store as rs
    doj_rows = [
        {"npi": "1000000001", "brain_rank": 4, "doj_priority_area": "Hospice"},
        {"npi": "1000000002", "brain_rank": 37, "doj_priority_area": "Home health care"},
    ]
    fake = {"top": [{"npi": "1000000009", "brain_rank": 1}], "doj_top": doj_rows,
            "doj_priority_total": 2}
    monkeypatch.setattr(fb, "_get_top_frauds", lambda limit, force: fake)
    monkeypatch.setattr(rs, "get_queue_statuses",
                        lambda npis: {"1000000001": "doj_filed"})

    main = fb.get_top_frauds(10)
    assert [e["npi"] for e in main["top"]] == ["1000000009"]

    doj = fb.get_top_frauds(10, doj_only=True)
    assert doj["doj_only"] is True
    assert [(e["npi"], e["brain_rank"]) for e in doj["top"]] == [("1000000002", 37)]
