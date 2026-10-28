"""Synthetic scoring contracts: no provider data, network, or startup."""
from services import anomaly_detector as detector
from services import risk_scorer, scan_engine


def complete(coroutine):
    # These mocks never suspend. Avoid Windows event-loop socketpair creation,
    # unavailable inside the filesystem/network sandbox.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("Synthetic coroutine unexpectedly suspended")


def test_sparse_cohort_is_unknown_not_absolute_fraud_threshold():
    result = detector.claims_per_bene_anomaly({"claims_per_beneficiary": 500})
    assert not result["flagged"]
    assert result["score"] == 0
    assert "insufficient" in result["reason"]


def test_missing_denominator_is_not_phantom_billing():
    result = detector.bene_concentration({"total_claims": 500})
    assert not result["flagged"]
    assert result["score"] == 0


def test_live_uses_identical_batch_signal_runner(monkeypatch):
    row = {"npi": "0000000000", "total_paid": 100, "total_claims": 10}
    codes = [{"hcpcs_code": "A", "total_paid": 100}]
    timeline = [{"month": "2024-01", "total_paid": 100}]
    cohort = ({"A": (1.0, 2.0)}, {"A": (3.0, 4.0)}, 5.0, 6.0)
    async def query(sql, params):
        return codes if "GROUP BY HCPCS_CODE" in sql else timeline
    async def cohorts():
        return cohort
    monkeypatch.setattr(risk_scorer, "query_async", query)
    monkeypatch.setattr(risk_scorer, "canonical_cohort_stats", cohorts)
    monkeypatch.setattr(risk_scorer, "compute_address_clusters", lambda: {})
    monkeypatch.setattr(risk_scorer, "compute_auth_official_clusters", lambda: {})
    async def gather(*coroutines):
        return [await item for item in coroutines]
    monkeypatch.setattr(risk_scorer.asyncio, "gather", gather)
    seen = []
    def runner(*args):
        seen.append(args)
        return {"risk_score": 12, "flags": [], "signal_results": [{"signal": "contract"}]}
    monkeypatch.setattr(scan_engine, "_score_provider", runner)
    monkeypatch.setattr(scan_engine, "_import_signals", lambda: {})
    result = complete(risk_scorer.score_provider(row["npi"], row))
    assert result["risk_score"] == 12
    assert seen[0][0:6] == (row, codes, timeline, row["npi"], "A", cohort[0])
    assert seen[0][6:9] == cohort[1:]


def test_canonical_cohort_ignores_sparse_ratios(monkeypatch):
    async def query(sql):
        assert "PARTITION BY npi ORDER BY paid DESC, code ASC" in sql
        assert "WHERE HCPCS_CODE =" not in sql
        return [{"code": "A", "mean_rpb": 10, "std_rpb": 2, "n_rpb": 3,
                 "mean_cpb": 100, "std_cpb": 20, "n_cpb": 2,
                 "mean_spend": 1000, "std_spend": 100}]
    monkeypatch.setattr(risk_scorer, "query_async", query)
    assert complete(risk_scorer.canonical_cohort_stats()) == ({"A": (10, 2)}, {}, 1000, 100)


def test_cohort_sql_uses_all_codes_of_matching_dominant_providers(monkeypatch):
    import duckdb
    import re
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE source (BILLING_PROVIDER_NPI_NUM VARCHAR, HCPCS_CODE VARCHAR, TOTAL_PAID DOUBLE, TOTAL_CLAIMS DOUBLE, TOTAL_UNIQUE_BENEFICIARIES DOUBLE)")
        # Three A-dominant providers: whole-provider ratios 10, 20, 30.
        # A fourth provider bills A but is B-dominant and must be excluded.
        con.executemany("INSERT INTO source VALUES (?, ?, ?, ?, ?)", [
            ("1", "A", 60, 6, 3), ("1", "B", 40, 4, 7),
            ("2", "A", 150, 15, 5), ("2", "B", 50, 5, 5),
            ("3", "A", 200, 20, 5), ("3", "B", 100, 10, 5),
            ("4", "A", 10, 1, 1), ("4", "B", 990, 99, 9),
        ])
        async def query(sql):
            cursor = con.execute(re.sub(r"read_parquet\('[^']*'\)", "source", sql))
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        monkeypatch.setattr(risk_scorer, "query_async", query)
        rpb, cpb, _, _ = complete(risk_scorer.canonical_cohort_stats())
        assert rpb["A"] == (20.0, 10.0)
        assert cpb["A"] == (2.0, 1.0)
        assert "B" not in rpb
    finally:
        con.close()


def test_cohort_cache_expires_and_invalidates_on_source_change(monkeypatch, tmp_path):
    source = tmp_path / "synthetic.parquet"
    source.write_bytes(b"first")
    monkeypatch.setattr(risk_scorer, "get_parquet_path", lambda: str(source))
    monkeypatch.setattr(risk_scorer, "_cohort_cache", None)
    clock = [0.0]
    monkeypatch.setattr(risk_scorer.time, "monotonic", lambda: clock[0])
    calls = []
    async def query(sql):
        calls.append(sql)
        return [{"code": "A", "mean_rpb": len(calls), "std_rpb": 1, "n_rpb": 3,
                 "mean_cpb": 1, "std_cpb": 1, "n_cpb": 3,
                 "mean_spend": 1, "std_spend": 1}]
    monkeypatch.setattr(risk_scorer, "query_async", query)
    first = complete(risk_scorer.canonical_cohort_stats())
    first[0].clear()  # callers cannot mutate the cached cohort
    assert complete(risk_scorer.canonical_cohort_stats())[0]["A"][0] == 1
    assert len(calls) == 1
    source.write_bytes(b"replacement-with-different-size")
    assert complete(risk_scorer.canonical_cohort_stats())[0]["A"][0] == 2
    clock[0] += risk_scorer.COHORT_CACHE_TTL_SECONDS
    assert complete(risk_scorer.canonical_cohort_stats())[0]["A"][0] == 3
    assert len(calls) == 3


def test_unversioned_remote_cohorts_never_reuse_cache(monkeypatch):
    monkeypatch.setattr(risk_scorer, "get_parquet_path", lambda: "https://example.invalid/data.parquet")
    monkeypatch.setattr(risk_scorer, "_cohort_cache", None)
    calls = []
    async def query(sql):
        calls.append(sql)
        return []
    monkeypatch.setattr(risk_scorer, "query_async", query)
    complete(risk_scorer.canonical_cohort_stats())
    complete(risk_scorer.canonical_cohort_stats())
    assert len(calls) == 2


def test_metadata_cannot_attach_unrelated_cohort_provenance(monkeypatch):
    monkeypatch.setattr(risk_scorer, "_last_cohort_result", ({"A": (1, 2)}, {"A": (3, 4)}, 5, 6))
    monkeypatch.setattr(risk_scorer, "_cohort_observation", {"status": "local_snapshot_recorded"})
    assert risk_scorer.cohort_observation("A", (1, 2), (3, 4), (5, 6))["status"] == "local_snapshot_recorded"
    assert risk_scorer.cohort_observation("A", (99, 2), (3, 4), (5, 6))["status"] == "unknown"


def test_slim_projection_keeps_new_metadata_without_fabricating_legacy():
    from core.store import _SLIM_FIELDS
    assert "scoring_metadata" in _SLIM_FIELDS
    legacy = {"npi": "0000000000", "risk_score": 10}
    assert "scoring_metadata" not in {key: legacy[key] for key in _SLIM_FIELDS if legacy.get(key) is not None}


def test_shared_runner_records_exact_statistics_and_denominator(monkeypatch):
    import services.feedback_tracker as feedback
    monkeypatch.setattr(feedback, "composite_with_feedback", lambda signals: 0)
    def no_signal(*args):
        return {"signal": "synthetic", "score": 0, "weight": 0, "flagged": False, "reason": "fixture"}
    detectors = {key: no_signal for key in scan_engine._import_signals()}
    monkeypatch.setattr(risk_scorer, "_last_cohort_result", None)
    result = scan_engine._score_provider({}, [], [], "0000000000", "A",
                                        {"A": (10, 2)}, {"A": (4, 1)}, 500, 100, {}, {}, detectors)
    metadata = result["scoring_metadata"]
    assert metadata["peer_statistics_used"]["revenue_per_summed_count"] == {"mean": 10, "stddev": 2}
    assert metadata["peer_statistics_used"]["total_paid"] == {"mean": 500, "stddev": 100}
    assert "not unique patients" in metadata["denominator_semantics"]
    assert metadata["cohort_source_snapshot"]["status"] == "unknown"
