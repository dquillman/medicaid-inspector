"""
Regression test (audit 2026-10-24, item 6): a missing or renamed dataset
column must surface as an explicit "missing_columns" status, not silently
read as all-null/zero downstream. This check must be runnable regardless of
is_local() — it's metadata-only (DESCRIBE), never scans row data.
"""
import asyncio

import services.data_validator as dv


def test_check_schema_reports_missing_columns(monkeypatch):
    async def _fake_query_async(sql, *a, **k):
        # Simulate a dataset missing TOTAL_CLAIMS and with one extra column.
        return [
            {"column_name": "BILLING_PROVIDER_NPI_NUM"},
            {"column_name": "HCPCS_CODE"},
            {"column_name": "CLAIM_FROM_MONTH"},
            {"column_name": "TOTAL_PAID"},
            {"column_name": "TOTAL_UNIQUE_BENEFICIARIES"},
            {"column_name": "SOME_NEW_COLUMN"},
        ]
    monkeypatch.setattr("data.duckdb_client.query_async", _fake_query_async)
    monkeypatch.setattr("data.duckdb_client.get_parquet_path", lambda: "fake.parquet")

    result = asyncio.run(dv.check_schema())

    assert result["status"] == "missing_columns"
    assert result["missing_columns"] == ["TOTAL_CLAIMS"]
    assert result["unexpected_columns"] == ["SOME_NEW_COLUMN"]


def test_check_schema_ok_when_all_expected_columns_present(monkeypatch):
    async def _fake_query_async(sql, *a, **k):
        return [{"column_name": c} for c in sorted(dv.EXPECTED_COLUMNS)]
    monkeypatch.setattr("data.duckdb_client.query_async", _fake_query_async)
    monkeypatch.setattr("data.duckdb_client.get_parquet_path", lambda: "fake.parquet")

    result = asyncio.run(dv.check_schema())

    assert result["status"] == "ok"
    assert result["missing_columns"] == []


def test_check_schema_failure_stays_an_explicit_error_not_ok(monkeypatch):
    async def _fake_query_async(sql, *a, **k):
        raise RuntimeError("remote parquet unreachable")
    monkeypatch.setattr("data.duckdb_client.query_async", _fake_query_async)
    monkeypatch.setattr("data.duckdb_client.get_parquet_path", lambda: "fake.parquet")

    result = asyncio.run(dv.check_schema())

    assert result["status"] == "error"
    assert result["missing_columns"] is None  # unknown, not silently "ok"
