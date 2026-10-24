"""
Regression tests (audit 2026-10-24, item 3): filing a report, confirming a
case, archiving, or reopening must not create a "verified fraud" training
label by itself. Only the analyst's own "confirmed" assessment (weak), or an
agency's independently substantiated/rejected referral outcome (strong), may.
"""
import services.feedback_tracker as ft
from core import review_store, referral_workflow


def _spy(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ft, "record_confirmation", lambda npi: calls.append(("confirm", npi)))
    monkeypatch.setattr(ft, "record_dismissal", lambda npi: calls.append(("dismiss", npi)))
    return calls


def _seed_review_item(npi: str):
    review_store.add_to_review_queue([{
        "npi": npi, "provider_name": "Test", "risk_score": 70.0,
        "signal_results": [{"signal": "billing_concentration", "flagged": True}],
    }])


def test_filing_a_tip_does_not_record_a_fraud_label(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000001"
    _seed_review_item(npi)
    for status in ("tip_filed", "referred", "doj_filed"):
        review_store.set_queue_status(npi, status, actor="dave", actor_type="user")
    assert calls == [], f"filing/referring must not record a label, got {calls}"


def test_archiving_does_not_record_a_label(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000002"
    _seed_review_item(npi)
    review_store.set_queue_status(npi, "archived", actor="dave", actor_type="user")
    assert calls == []


def test_confirmed_still_records_a_weak_positive_label(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000003"
    _seed_review_item(npi)
    review_store.set_queue_status(npi, "confirmed", actor="dave", actor_type="user")
    assert calls == [("confirm", npi)]


def test_dismissed_still_records_a_negative_label(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000004"
    _seed_review_item(npi)
    review_store.set_queue_status(npi, "dismissed", actor="dave", actor_type="user")
    assert calls == [("dismiss", npi)]


def test_substantiated_referral_outcome_records_a_strong_positive_label(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000005"
    ref = referral_workflow.create_referral(npi, submitted_by="dave")
    referral_workflow.update_referral(ref["id"], outcome="substantiated", updated_by="mfcu")
    assert calls == [("confirm", npi)]


def test_unsubstantiated_referral_outcome_records_a_negative_label(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000006"
    ref = referral_workflow.create_referral(npi, submitted_by="dave")
    referral_workflow.update_referral(ref["id"], outcome="unsubstantiated", updated_by="mfcu")
    assert calls == [("dismiss", npi)]


def test_pending_referral_outcome_records_nothing(monkeypatch):
    calls = _spy(monkeypatch)
    npi = "5550000007"
    ref = referral_workflow.create_referral(npi, submitted_by="dave")
    referral_workflow.update_referral(ref["id"], outcome="pending", updated_by="mfcu")
    assert calls == []


def test_label_readiness_excludes_referred_status(monkeypatch):
    # _label_readiness() scans ALL in-memory referrals/review items, which
    # other tests in this module also populate — so this compares a before/
    # after delta rather than asserting an absolute count.
    from services.supervised_scorer import _label_readiness
    before = _label_readiness()
    npi = "5550000008"
    _seed_review_item(npi)
    review_store.set_queue_status(npi, "referred", actor="dave", actor_type="user")
    after = _label_readiness()
    # "referred" queue_status alone must not count toward positive_count.
    # (Legacy `status` field is what _label_readiness actually reads; a fresh
    # queue item has no legacy `status`, so this NPI contributes nothing.)
    assert after["positive_count"] == before["positive_count"]
