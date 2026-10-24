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

    # A genuinely different data source (pharmacy diversion profile) must be
    # unaffected — it should still score as real corroboration.
    pharmacy_hit = next(e for d, e in by_detail.items() if d.startswith("Pharmacy high-risk"))
    assert pharmacy_hit["points"] > 0.0
    assert pharmacy_hit["source"] == "Independent analysis"
