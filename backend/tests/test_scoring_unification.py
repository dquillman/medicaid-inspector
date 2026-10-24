"""
Regression test (audit 2026-10-24, item 5): the live scoring path
(risk_scorer.score_provider) used to call claims_per_bene_anomaly with NO
peer stats at all, so it always fell back to the absolute >100-claims
threshold — while the batch path (scan_engine) compared against a real peer
cohort whenever >=3 peers existed. The same provider could be flagged by one
path and not the other purely because of which code path scored it. Both
paths must now use the SAME peer cohort for both revenue_per_bene_outlier and
claims_per_bene_anomaly.
"""
import asyncio

import services.risk_scorer as rs


def _fake_query_async(peer_row):
    async def _query(sql, params=()):
        if "mean_rpb" in sql or "peer_n" in sql:
            return [peer_row]
        if "CLAIM_FROM_MONTH" in sql:
            return []
        if "hcpcs_code" in sql:
            return []
        return []
    return _query


def test_live_path_uses_real_cohort_for_claims_per_bene_when_enough_peers(monkeypatch):
    # A provider with 60 claims/beneficiary: under the old no-peer-stats
    # default this is BELOW the absolute >100 threshold (not flagged) — but
    # a real peer cohort with a tight distribution (mean=10, std=2) makes it
    # a 25-sigma outlier, which is what a "matching cohort" comparison should
    # catch and the absolute threshold alone would miss.
    monkeypatch.setattr(rs, "query_async", _fake_query_async({
        "mean_rpb": 100.0, "std_rpb": 20.0,
        "mean_cpb": 10.0, "std_cpb": 2.0,
        "peer_n": 50,
    }))
    monkeypatch.setattr(rs, "compute_address_clusters", lambda: {})
    monkeypatch.setattr(rs, "compute_auth_official_clusters", lambda: {})

    provider_agg = {
        "npi": "1234567890", "claims_per_beneficiary": 60.0,
        "revenue_per_beneficiary": 50.0, "total_claims": 100,
    }
    result = asyncio.run(rs.score_provider("1234567890", provider_agg))
    cpb_signal = next(s for s in result["signal_results"] if s["signal"] == "claims_per_bene_anomaly")

    assert cpb_signal["flagged"] is True, (
        "with a real matching cohort (mean=10, std=2), 60 claims/beneficiary "
        f"is a 25-sigma outlier and must flag: {cpb_signal}"
    )
    assert "insufficient peer data" not in cpb_signal["reason"].lower()


def test_live_path_falls_back_honestly_when_cohort_too_small(monkeypatch):
    monkeypatch.setattr(rs, "query_async", _fake_query_async({
        "mean_rpb": 100.0, "std_rpb": 20.0,
        "mean_cpb": 10.0, "std_cpb": 2.0,
        "peer_n": 2,  # below the >=3 minimum both paths require
    }))
    monkeypatch.setattr(rs, "compute_address_clusters", lambda: {})
    monkeypatch.setattr(rs, "compute_auth_official_clusters", lambda: {})

    provider_agg = {
        "npi": "1234567891", "claims_per_beneficiary": 60.0,
        "revenue_per_beneficiary": 50.0, "total_claims": 100,
    }
    result = asyncio.run(rs.score_provider("1234567891", provider_agg))
    cpb_signal = next(s for s in result["signal_results"] if s["signal"] == "claims_per_bene_anomaly")
    # 60 < the absolute 100 fallback threshold, and the cohort is too small
    # to use — must NOT flag, and must say so honestly.
    assert cpb_signal["flagged"] is False
    assert "insufficient peer data" in cpb_signal["reason"].lower()
