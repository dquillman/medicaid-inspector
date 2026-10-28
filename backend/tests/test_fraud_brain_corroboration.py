"""
Regression test (audit 2026-10-24): the Fraud Brain board must not score
aggregate code-mix heuristics (unbundling / place-of-service / modifier
abuse) as if they were independent claim-level corroboration — this dataset
has no claim-line, modifier, or place-of-service fields. These heuristics
should still appear as leads, but must contribute zero points to the
composite score, and must not be labeled "Independent analysis".
"""
from services import fraud_brain as fb


def test_unbundling_pos_modifiers_score_zero_and_are_labeled_as_heuristics(
    client, auth_headers, monkeypatch
):
    npi = "1234567890"  # one of conftest's SAMPLE_PROVIDERS

    monkeypatch.setattr(
        fb, "_corroboration_index",
        lambda: {npi: ["unbundling", "pos", "modifiers", "pharmacy"]},
    )
    fb.invalidate_cache()

    resp = client.get("/api/fraud-brain/top", params={"limit": 10, "refresh": True},
                       headers=auth_headers)
    assert resp.status_code == 200
    top = resp.json()["top"]
    entry = next((p for p in top if p.get("npi") == npi), None)
    assert entry is not None, "test NPI should be present on the board"

    evidence = entry["evidence"]
    by_detail = {e["detail"]: e for e in evidence}

    for key_substr in ("Unbundling pattern", "Place-of-service anomaly", "Modifier abuse pattern"):
        hit = next(e for d, e in by_detail.items() if d.startswith(key_substr))
        assert hit["points"] == 0.0, f"{key_substr} must not contribute points: {hit}"
        assert hit["source"] != "Independent analysis", (
            f"{key_substr} must not be labeled 'Independent analysis': {hit}"
        )

    # Pharmacy profile reuses aggregate drug-code inputs; a different analysis
    # is not automatically an independent source of evidence.
    pharmacy_hit = next(e for d, e in by_detail.items() if d.startswith("Pharmacy high-risk"))
    assert pharmacy_hit["points"] == 0.0
    assert pharmacy_hit["evidence_class"] == "aggregate_hypothesis"
    assert pharmacy_hit["independent"] is False


def test_historical_rows_are_annotated_not_hidden(client, auth_headers, monkeypatch):
    import core.store as store
    existing = store.get_prescanned()
    historical = {**existing[0], "npi": "1234567890", "last_month": "2018-01",
                  "risk_score": 80, "flag_count": 3}
    monkeypatch.setattr(store, "get_prescanned", lambda: [historical])
    monkeypatch.setattr(fb, "_corroboration_index", lambda: {})
    fb.invalidate_cache()
    result = fb.compute_top_frauds(10)
    assert result["top"][0]["npi"] == "1234567890"
    assert result["top"][0]["recency"] == "older"
    assert result["excluded"]["expired"] == 0


def test_all_current_analysis_sources_are_not_independent():
    assert set(fb._ANALYSIS_SOURCES) == fb._CORRELATED_NOT_INDEPENDENT
