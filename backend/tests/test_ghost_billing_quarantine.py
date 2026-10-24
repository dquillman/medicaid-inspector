"""
Regression test (audit 2026-10-24, item 4): ghost_billing must never flag or
score, even for a provider that would have tripped the old >50%-of-months-at-
exactly-12 rule, because no documented source ties a "12" suppression floor
to this dataset.
"""
from services.anomaly_detector import ghost_billing


def test_ghost_billing_never_flags_even_on_a_textbook_case():
    timeline = [
        {"total_paid": 5000.0, "total_unique_beneficiaries": 12} for _ in range(12)
    ]
    result = ghost_billing({}, timeline)
    assert result["flagged"] is False
    assert result["score"] == 0.0
    assert "12/12" in result["reason"]
    assert "not scored" in result["reason"].lower() or "informational" in result["reason"].lower()


def test_ghost_billing_handles_empty_timeline():
    result = ghost_billing({}, [])
    assert result["flagged"] is False
    assert result["score"] == 0.0
