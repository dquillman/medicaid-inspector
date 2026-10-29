"""Reliability gate for per-se 'paid while terminated' leads (audit 2026-10-28).
Synthetic NPIs only."""
from core.lead_quality import quality_flags


def _lead(**kw):
    base = {"npi": "1000000001", "kind": "paid_while_terminated", "state": "WA"}
    base.update(kw)
    return base


def test_clean_lead_has_no_flags():
    assert quality_flags(_lead(practice_state="WA")) == []


def test_reinstated_is_flagged():
    assert quality_flags(_lead(reinstated_after=True)) == ["reinstated"]


def test_state_mismatch_is_flagged():
    # terminated in WA, practises in OR
    assert "state_mismatch" in quality_flags(_lead(practice_state="OR"))


def test_unknown_practice_state_is_not_a_mismatch():
    assert quality_flags(_lead()) == []


def test_blind_state_is_unobservable():
    flags = quality_flags(_lead(state="AZ", practice_state="NM"), ["NM", "OR"])
    assert "unobservable_state" in flags and "state_mismatch" in flags


def test_other_kinds_are_not_gated():
    assert quality_flags({"kind": "active_exclusion", "state": "NM", "practice_state": "AZ"}) == []


def test_case_insensitive_states():
    assert quality_flags(_lead(state="wa", practice_state="WA")) == []


def test_shortlist_drops_flagged_leads(monkeypatch):
    from core import perse_store
    from services import doj_shortlist
    leads = [
        _lead(npi="1000000001", paid_while_terminated=500000.0, last_month="2024-12", practice_state="WA"),
        _lead(npi="1000000002", paid_while_terminated=900000.0, last_month="2024-12", reinstated_after=True),
        _lead(npi="1000000003", paid_while_terminated=800000.0, last_month="2024-12", practice_state="OR"),
    ]
    monkeypatch.setattr(perse_store, "list_leads", lambda **k: {"leads": leads, "total": 3})
    monkeypatch.setattr(perse_store, "blind_states", lambda: [])
    out = doj_shortlist.build_shortlist()
    npis = {r["npi"] for r in out["leads"] if r.get("kind") == "paid_while_terminated"}
    assert "1000000001" in npis
    assert not ({"1000000002", "1000000003"} & npis)
    assert out["dropped"]["unreliable_status"] == 2
