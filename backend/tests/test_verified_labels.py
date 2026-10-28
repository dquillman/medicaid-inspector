"""Training labels require documented independent findings, not workflow actions."""
from core import referral_workflow as referrals
from services import supervised_scorer


def test_only_documented_findings_are_labels(monkeypatch):
    outcomes = ["substantiated", "unsubstantiated", "criminal_charges", "civil_action", "settlement", "declined", "pending"]
    rows = [{"npi": f"fixture-{i}", "outcome": outcome, "evidence_reference": "agency record"} for i, outcome in enumerate(outcomes)]
    rows.append({"npi": "legacy", "outcome": "substantiated"})
    monkeypatch.setattr(referrals, "get_referrals", lambda: rows)
    assert referrals.get_verified_labels() == {"fixture-0": 1, "fixture-1": 0}
    readiness = supervised_scorer._label_readiness()
    assert readiness["total_labeled"] == 2
    assert readiness["can_train"] is False


def test_conflicting_outcomes_remain_unknown(monkeypatch):
    monkeypatch.setattr(referrals, "get_referrals", lambda: [
        {"npi": "fixture", "outcome": "substantiated", "evidence_reference": "record A"},
        {"npi": "fixture", "outcome": "unsubstantiated", "evidence_reference": "record B"},
    ])
    assert referrals.get_verified_labels() == {}


def test_definitive_outcome_requires_evidence_before_mutation(monkeypatch):
    import pytest
    row = {"id": 1, "npi": "fixture", "stage": "submitted", "outcome": None, "history": []}
    monkeypatch.setattr(referrals, "_referrals", [row])
    with pytest.raises(ValueError, match="evidence reference"):
        referrals.update_referral(1, stage="under_investigation", outcome="substantiated")
    assert row["stage"] == "submitted"
    assert row["outcome"] is None


def test_retrain_invalidates_old_predictions_immediately(monkeypatch):
    class Timer:
        daemon = False
        def __init__(self, *args): pass
        def start(self): pass
        def cancel(self): pass
    monkeypatch.setattr(supervised_scorer.threading, "Timer", Timer)
    monkeypatch.setattr(supervised_scorer, "_predictions", {"fixture": {"fraud_probability": 0.99}})
    monkeypatch.setattr(supervised_scorer, "_training_metrics", {"trained": True})
    monkeypatch.setattr(supervised_scorer, "_model", object())
    monkeypatch.setattr(supervised_scorer, "_scaler", object())
    monkeypatch.setattr(supervised_scorer, "_load_attempted", False)
    monkeypatch.setattr(supervised_scorer, "_retrain_timer", None)
    supervised_scorer.schedule_retrain()
    assert supervised_scorer._predictions == {}
    assert supervised_scorer._training_metrics == {}
    assert supervised_scorer._model is None


def test_withdrawing_outcome_clears_independent_feedback_but_preserves_other_findings(monkeypatch):
    from services import feedback_tracker as feedback
    calls = []
    monkeypatch.setattr(referrals, "_save_to_disk", lambda: None)
    monkeypatch.setattr(supervised_scorer, "schedule_retrain", lambda: None)
    monkeypatch.setattr(feedback, "clear_label", lambda npi, **kwargs: calls.append(("clear", kwargs)))
    monkeypatch.setattr(feedback, "record_confirmation", lambda npi, **kwargs: calls.append(("positive", kwargs)))
    rows = [{"id": 1, "npi": "fixture", "stage": "outcome_received", "outcome": "substantiated", "evidence_reference": "agency A", "history": [], "created_at": 1}]
    monkeypatch.setattr(referrals, "_referrals", rows)
    referrals.update_referral(1, outcome="pending")
    assert calls[-1] == ("clear", {"source": "independent_outcome"})
    rows.append({"id": 2, "npi": "fixture", "outcome": "substantiated", "evidence_reference": "agency B", "created_at": 2})
    referrals.update_referral(1, outcome="declined", evidence_reference="")
    assert calls[-1] == ("positive", {"source": "independent_outcome", "evidence_reference": "agency B"})
