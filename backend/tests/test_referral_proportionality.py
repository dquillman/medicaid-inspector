"""
Regression test (audit 2026-10-24, item 7): a high risk score alone must not
produce a "PRIORITY REFERRAL" / "credible allegation of fraud" / payment-
suspension recommendation when enrichment didn't complete or there's no
corroborating signal beyond the one statistical outlier.
"""
from services.narrative_generator import _build_actions_section


def _flag(signal: str) -> dict:
    return {"signal": signal, "flagged": True, "score": 0.9, "weight": 20}


def test_high_score_without_enrichment_does_not_get_priority_referral():
    provider = {
        "risk_score": 80,
        "signal_results": [_flag("revenue_per_bene_outlier"), _flag("billing_concentration")],
        # no provider_name / specialty => enrichment incomplete
    }
    content = _build_actions_section(provider)["content"]
    assert "PRIORITY REFERRAL" not in content
    assert "PAYMENT SUSPENSION" not in content
    assert "NOT YET REFERRAL-READY" in content


def test_high_score_with_only_one_signal_does_not_get_priority_referral():
    provider = {
        "risk_score": 80,
        "provider_name": "Acme Clinic", "specialty": "Internal Medicine",
        "signal_results": [_flag("revenue_per_bene_outlier")],  # only one
    }
    content = _build_actions_section(provider)["content"]
    assert "PRIORITY REFERRAL" not in content
    assert "NOT YET REFERRAL-READY" in content


def test_high_score_with_enrichment_and_corroboration_gets_priority_referral():
    provider = {
        "risk_score": 80,
        "provider_name": "Acme Clinic", "specialty": "Internal Medicine",
        "signal_results": [_flag("revenue_per_bene_outlier"), _flag("billing_concentration")],
    }
    content = _build_actions_section(provider)["content"]
    assert "PRIORITY REFERRAL" in content
    assert "credible allegation of fraud" not in content  # no longer an absolute claim


def test_oig_excluded_action_does_not_claim_confirmed_recovery():
    provider = {
        "risk_score": 90,
        "provider_name": "Acme Clinic", "specialty": "Internal Medicine",
        "signal_results": [_flag("oig_excluded"), _flag("billing_concentration")],
    }
    content = _build_actions_section(provider)["content"]
    assert "initiate overpayment recovery" not in content
    assert "suspected-overpayment review" in content
