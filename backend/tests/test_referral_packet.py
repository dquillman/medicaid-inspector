"""
Unit tests for the referral-packet assembler + renderer.

These test the pure builder/renderer directly with synthetic provider dicts, so
they need no FastAPI app, auth, parquet, or network. They cover the two cases
called out in the spec: a provider with MULTIPLE fired signals, and the edge
case of a provider with NONE.
"""
import asyncio
import os
import sys

# Allow both `pytest` (rootdir=backend) and `python tests/test_referral_packet.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.referral_packet import build_referral_packet, render_referral_html


def _provider(npi, *, risk, signals, timeline=None, hcpcs=None, nppes=None):
    return {
        "npi": npi,
        "provider_name": "TEST PROVIDER LLC",
        "risk_score": risk,
        "signal_results": signals,
        "total_paid": 500_000,
        "total_claims": 4200,
        "total_beneficiaries": 300,
        "active_months": 12,
        "first_month": "2023-01",
        "last_month": "2023-12",
        "distinct_hcpcs": 3,
        "top_hcpcs": "T1019",
        "timeline": timeline or [],
        "hcpcs": hcpcs or [],
        "nppes": nppes or {
            "name": "TEST PROVIDER LLC",
            "entity_type": "NPI-2",
            "address": {"line1": "1 Main St", "city": "Columbus", "state": "OH", "zip": "43201"},
            "taxonomy": {"description": "Behavioral Health", "code": "251S00000X"},
            "authorized_official": {"name": "", "title": ""},
            "status": "A",
        },
    }


MULTI_SIGNALS = [
    {"signal": "billing_concentration", "flagged": True, "score": 0.81, "weight": 2,
     "reason": "T1019 represents 98% of billing - extreme single-code dominance"},
    {"signal": "revenue_per_bene_outlier", "flagged": True, "score": 0.90, "weight": 10,
     "reason": "Revenue/beneficiary 3.4 sigma above same-code peers"},
    {"signal": "claims_per_bene_anomaly", "flagged": True, "score": 0.72, "weight": 8,
     "reason": "17.4 claims per beneficiary vs peer median of 4.1"},
    {"signal": "upcoding_pattern", "flagged": False, "score": 0.10, "weight": 10, "reason": ""},
]


def _build(npi, **kw):
    # build_referral_packet is async but does no real I/O for synthetic inputs
    # (exclusion/network/narrative enrichment fail-soft to None).
    return asyncio.run(build_referral_packet(npi, provider=_provider(npi, **kw)))


def test_packet_multi_signal_structure():
    pkt = _build("1234567890", risk=74.0, signals=MULTI_SIGNALS,
                 timeline=[{"month": "2023-0%d" % m, "total_paid": 10000 * m,
                            "total_claims": 100 * m, "total_unique_beneficiaries": 20 * m}
                           for m in range(1, 10)])
    assert pkt["npi"] == "1234567890"
    assert pkt["risk"]["score"] == 74.0
    # 3 of 4 signals flagged
    assert pkt["risk"]["flagged_count"] == 3
    assert pkt["risk"]["total_signals"] == 4
    # every flagged signal carries methodology + citations (reused _SIGNAL_META)
    flagged = [s for s in pkt["signals"] if s["flagged"]]
    assert len(flagged) == 3
    assert all(s["methodology"] for s in flagged)
    assert all(s["citations"] for s in flagged)
    assert all(s["reason"] for s in flagged)
    # consolidated citation trail is populated and de-duplicated
    assert pkt["citations"]
    assert len(pkt["citations"]) == len(set(pkt["citations"]))
    # recommendation escalates at risk >= 50
    assert "IMMEDIATE REFERRAL" in pkt["recommendation"]["level"]


def test_packet_renders_html_multi_signal():
    pkt = _build("1234567890", risk=74.0, signals=MULTI_SIGNALS,
                 timeline=[{"month": "2023-01", "total_paid": 5000, "total_claims": 50,
                            "total_unique_beneficiaries": 10},
                           {"month": "2023-02", "total_paid": 90000, "total_claims": 900,
                            "total_unique_beneficiaries": 120}])
    html = render_referral_html(pkt)
    assert html.startswith("<!DOCTYPE html>")
    # all 11 sections present
    for heading in ["1. Provider Identification", "2. Risk Score Summary",
                    "3. Federal Exclusion Status", "4. Billing Summary",
                    "5. Top HCPCS Codes", "6. Monthly Billing Timeline",
                    "7. Fraud Signal Analysis", "8. Network Findings",
                    "9. Plain-English Narrative", "10. Referral Recommendation",
                    "11. Source"]:
        assert heading in html, f"missing section: {heading}"
    # methodology, proof, and a citation surface in the signal section
    assert "Methodology:" in html
    assert "Finding (proof):" in html
    assert "Regulatory basis:" in html
    # visual timeline chart rendered (2+ months)
    assert "<svg" in html
    # no unrendered template braces / None leakage
    assert "None" not in html.replace("Nonexistent", "")


def test_packet_zero_signals_edge_case():
    pkt = _build("1999999999", risk=4.0, signals=[
        {"signal": "billing_concentration", "flagged": False, "score": 0.1, "weight": 2, "reason": ""},
        {"signal": "upcoding_pattern", "flagged": False, "score": 0.0, "weight": 10, "reason": ""},
    ])
    assert pkt["risk"]["flagged_count"] == 0
    # no citations when nothing fired
    assert pkt["citations"] == []
    assert "CONTINUE MONITORING" in pkt["recommendation"]["level"]
    html = render_referral_html(pkt)
    assert html.startswith("<!DOCTYPE html>")
    # renders cleanly with the "no citations" fallback and no crash
    assert "No signal-specific citations" in html
    assert "7. Fraud Signal Analysis" in html


def test_packet_no_timeline_uses_note_not_blank():
    pkt = _build("1888888888", risk=30.0, signals=MULTI_SIGNALS, timeline=[])
    html = render_referral_html(pkt, slim_note="running on slim cache")
    assert "Monthly timeline detail is not loaded" in html
    assert "Data note: running on slim cache" in html


if __name__ == "__main__":
    # Allow running without pytest: `python tests/test_referral_packet.py`
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failed else 0)
