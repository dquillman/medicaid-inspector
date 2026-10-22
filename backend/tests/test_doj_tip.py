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
