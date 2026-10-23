"""
Update notes for filed tips that left out the per-se key finding.

Rule under test: a tip on a revoked / terminated / dead-NPI provider that never
said so gets an update note with the finding and the barred amount; a tip that
already said it, a weak NPI gap and a recovery lead get none.
"""
import pytest

from core import oig_tips_store, perse_store
from services import tip_supplements

OLD = tip_supplements.KEY_FINDING_FIX_TS - 86400
NEW = tip_supplements.KEY_FINDING_FIX_TS + 86400

LEADS = {
    "1000000001": {"npi": "1000000001", "kind": "medicare_revoked_billing", "state": "TX",
                   "revocation_date": "2022-12-30", "paid_after_revocation": 4_648_497.55,
                   "total_paid": 10_473_627, "citation": "42 CFR 455.416(c)"},
    "1000000002": {"npi": "1000000002", "kind": "deactivated_window", "weak": True, "gap_days": 66,
                   "deactivation_date": "2023-01-01", "reactivation_date": "2023-03-08",
                   "paid_during_deactivation": 891_746, "total_paid": 2_000_000},
    "1000000003": {"npi": "1000000003", "kind": "recovery_lead", "exclusion_date": "2025-01-01",
                   "total_paid": 50_000},
    "1000000004": {"npi": "1000000004", "kind": "medicare_revoked_billing",
                   "revocation_date": "2021-05-01", "paid_after_revocation": 120_000,
                   "total_paid": 300_000},
    "1000000005": {"npi": "1000000005", "kind": "medicare_revoked_billing",
                   "revocation_date": "2021-05-01", "paid_after_revocation": 90_000,
                   "total_paid": 200_000},
}


def _tip(i, npi, filed_at, text="", dest="doj"):
    return {"id": f"t{i}", "npi": npi, "destination": dest, "provider_name": f"P{i}",
            "reference_number": f"TFF-2026-{i}", "status": "filed", "filed_at": filed_at,
            "filed_text": text, "history": []}


@pytest.fixture
def tips(tmp_path, monkeypatch):
    monkeypatch.setattr(perse_store, "get_lead", lambda npi: LEADS.get(npi))
    monkeypatch.setattr(oig_tips_store, "_FILE", tmp_path / "oig_tips.json")
    monkeypatch.setattr(oig_tips_store, "_loaded", True)
    import core.gcs_sync as gs
    monkeypatch.setattr(gs, "upload_file", lambda *a, **k: None)
    rows = [
        _tip(1, "1000000001", OLD),                                   # no text, before the fix
        _tip(2, "1000000002", OLD),                                   # weak gap
        _tip(3, "1000000003", OLD),                                   # recovery lead
        _tip(4, "1000000004", NEW, "Suspected fraud. Payment per recipient is high."),
        _tip(5, "1000000005", NEW, "KEY FINDING: Medicare revoked this provider ..."),
        _tip(6, "1999999999", OLD),                                   # no per-se lead at all
    ]
    monkeypatch.setattr(oig_tips_store, "_tips", rows)
    return rows


def test_only_tips_missing_the_finding_get_a_note(tips):
    r = tip_supplements.find_supplements()
    got = {i["npi"]: i["coverage"] for i in r["items"]}
    assert got == {"1000000001": "likely_missing", "1000000004": "missing"}
    assert [s["npi"] for s in r["skipped"]] == ["1000000002"]


def test_note_carries_the_finding_amount_and_original_reference(tips):
    item = next(i for i in tip_supplements.find_supplements()["items"] if i["npi"] == "1000000001")
    text = item["text"]
    assert "TFF-2026-1" in text
    assert "KEY FINDING: Medicare revoked" in text
    assert "$4,648,498" in text
    assert "/methods" in text
    assert len(text) <= tip_supplements.DOJ_BOX_CAP


def test_logging_the_update_clears_the_flag_and_keeps_the_original_text(client, auth_headers, tips):
    r = client.get("/api/oig-tips/supplements", headers=auth_headers)
    assert r.status_code == 200
    note = next(i for i in r.json()["items"] if i["tip_id"] == "t4")
    r = client.post("/api/oig-tips/t4/supplement", headers=auth_headers,
                    json={"text": note["text"], "reference_number": "TFF-2026-999"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filed_text"].startswith("Suspected fraud.")
    assert body["supplements"][0]["reference_number"] == "TFF-2026-999"
    left = client.get("/api/oig-tips/supplements", headers=auth_headers).json()["items"]
    assert "t4" not in {i["tip_id"] for i in left}


def test_supplement_needs_text_and_a_real_tip(client, auth_headers, tips):
    assert client.post("/api/oig-tips/t4/supplement", headers=auth_headers,
                       json={"text": " "}).status_code == 400
    assert client.post("/api/oig-tips/nope/supplement", headers=auth_headers,
                       json={"text": "x"}).status_code == 404


SAMPLE = """DOJ CRIMINAL TIP REWARDS PILOT PROGRAM - Suspected Medicaid Provider Fraud
Submitted via the federal fraud portal: https://america.gov/fraud

SUBJECT OF COMPLAINT
  Provider name: TEST CARE, LLC
  NPI: 1000000001

NATURE OF THE ALLEGATION
  Automated analysis flagged this provider.

  ** KEY FINDING (verifiable from public records):
     Medicare revoked this provider's enrollment effective 2022-12-30 \u2014 still paid.
     Amount paid after Medicare revoked the provider: $4,648,498 **

  TOTAL MEDICAID PAID TO SUBJECT (period): $10,473,627

SUPPORTING INDICATORS (1)
  - Billing Ramp Rate: Billing grew 900% in first 6 months
      Regulatory basis: 42 CFR \u00a7 455.23
"""


def test_tip_pdf_is_a_real_pdf_with_the_text(client, auth_headers):
    r = client.post("/api/oig-tips/pdf", headers=auth_headers,
                    json={"npi": "1000000001", "text": SAMPLE, "provider_name": "TEST CARE, LLC"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert 'filename="DOJ-tip-1000000001.pdf"' in r.headers["content-disposition"]


def test_tip_pdf_needs_auth_and_text(client, auth_headers):
    assert client.post("/api/oig-tips/pdf", json={"npi": "1", "text": "x"}).status_code == 401
    assert client.post("/api/oig-tips/pdf", headers=auth_headers,
                       json={"npi": "1", "text": "  "}).status_code == 400
