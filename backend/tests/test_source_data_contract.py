"""Synthetic source-level contracts; no real provider records or source access."""
from services import data_validator as dv


def test_schema_rejects_unknown_types_and_boolean_amounts():
    issues = dv.schema_type_issues([
        {"column_name": "TOTAL_PAID", "column_type": "BOOLEAN"},
        {"column_name": "HCPCS_CODE"},
        {"column_name": "BILLING_PROVIDER_NPI_NUM", "column_type": "BIGINT"},
    ])
    assert set(issues) == {"TOTAL_PAID", "HCPCS_CODE"}


def test_suppression_and_missing_are_never_observed_zero():
    assert dv.beneficiary_count_state(None) == "missing"
    assert dv.beneficiary_count_state("suppressed") == "suppressed"
    assert dv.beneficiary_count_state("<11") == "suppressed"
    assert dv.beneficiary_count_state(0) == "zero"
    assert dv.beneficiary_count_state(12) == "observed"
    for value in [True, -1, 1.2, float("nan"), float("inf"), "junk"]:
        assert dv.beneficiary_count_state(value) == "invalid"


def _row(**updates):
    # Synthetic valid checksum generated exclusively for a test fixture.
    row = {"npi": "1234567893", "servicing_npi": None, "hcpcs_code": "A1234",
           "claim_from_month": "2024-01", "total_unique_beneficiaries": None}
    return {**row, **updates}


def test_source_grain_contains_servicing_identity_and_normalized_month():
    first = dv.source_record_contract(_row())
    assert first["source_grain_key"] == ("1234567893", "", "A1234", "2024-01")
    assert first["servicing_identity_state"] == "missing"
    assert first["beneficiary_count_state"] == "missing"
    second = dv.source_record_contract(_row(servicing_npi="1234567893", claim_from_month=202401))
    assert second["source_grain_key"] != first["source_grain_key"]
    assert second["source_grain_key"][-1] == "2024-01"


def test_source_period_and_identity_integrity():
    assert "outside_published_coverage_period" in dv.source_record_contract(_row(claim_from_month="2025-01"))["issues"]
    assert "invalid_source_month" in dv.source_record_contract(_row(claim_from_month="2024-13"))["issues"]
    assert "invalid_hcpcs_code" in dv.source_record_contract(_row(hcpcs_code="bad"))["issues"]
    assert "servicing_npi_invalid_identity" in dv.source_record_contract(_row(servicing_npi="oops"))["issues"]


def test_run_validation_wires_schema_grain_and_missing_states(monkeypatch):
    import data.duckdb_client as db
    async def query(sql):
        if sql.startswith("DESCRIBE"):
            return [{"column_name": c, "column_type": "DOUBLE" if c.startswith("TOTAL_") else "VARCHAR"} for c in dv.EXPECTED_COLUMNS]
        if "COUNT(*)" in sql:
            return [{"cnt": 3}]
        assert "SERVICING_PROVIDER_NPI_NUM" in sql
        return [_row(total_paid=100, total_claims=10), _row(total_paid=100, total_claims=10),
                _row(servicing_npi="1234567893", total_paid=100, total_claims=10, total_unique_beneficiaries="suppressed")]
    monkeypatch.setattr(db, "query_async", query)
    monkeypatch.setattr(db, "get_parquet_path", lambda: "synthetic.parquet")
    coroutine = dv.run_validation(3)
    try:
        coroutine.send(None)
    except StopIteration as done:
        result = done.value
    assert result["status"] == "complete"
    assert result["duplicate_source_grain_rows_in_sample"] == 1
    assert result["beneficiary_count_states"]["missing"] == 2
    assert result["beneficiary_count_states"]["suppressed"] == 1
    assert result["source_grain"] == ["billing_npi", "servicing_npi", "hcpcs_code", "month"]


def test_placeholder_servicing_is_coverage_without_inventing_identity():
    for value in [None, "", "  ", "null", "None", "N/A", "unknown", "0", 0, "-1"]:
        row = _row(servicing_npi=value)
        before = dict(row)
        result = dv.source_record_contract(row)
        assert not result["servicing_identity_join_eligible"]
        assert result["servicing_identity_state"] in ("missing", "placeholder")
        assert "servicing_npi_invalid_identity" not in result["issues"]
        assert result["servicing_identity_raw"] == value and row == before
    malformed = dv.source_record_contract(_row(servicing_npi="1234567890"))
    assert malformed["servicing_identity_state"] == "malformed"
    assert "servicing_npi_invalid_identity" in malformed["issues"]


def test_four_digit_code_is_an_alternate_shape_not_invented_hcpcs():
    row = _row(hcpcs_code="0450")
    result = dv.source_record_contract(row)
    assert result["source_code_raw"] == "0450" and row["hcpcs_code"] == "0450"
    assert result["source_code_state"] == "alternate_code_system_shape"
    assert result["issues"] == ["source_code_system_mismatch"]
    assert not result["hcpcs_inference_eligible"]
    # A syntactically matching code remains only a format match, not a claim
    # that a coding authority recognizes it.
    assert dv.source_record_contract(_row(hcpcs_code="XXXXX"))["source_code_state"] == "hcpcs_format"
    assert not dv.source_record_contract(_row(hcpcs_code="A12!4"))["hcpcs_inference_eligible"]


def test_seeded_source_sample_digest_and_admin_diagnostics(monkeypatch, tmp_path):
    import asyncio
    import duckdb
    import data.duckdb_client as db
    source = tmp_path / "synthetic.parquet"
    con = duckdb.connect(":memory:", config={"autoinstall_known_extensions": "false", "autoload_known_extensions": "false"})
    con.execute("CREATE TABLE fixture(BILLING_PROVIDER_NPI_NUM VARCHAR, SERVICING_PROVIDER_NPI_NUM VARCHAR, HCPCS_CODE VARCHAR, CLAIM_FROM_MONTH VARCHAR, TOTAL_PAID DOUBLE, TOTAL_CLAIMS BIGINT, TOTAL_UNIQUE_BENEFICIARIES BIGINT)")
    con.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ("1234567893", "null", "A1234", "2024-01", 2000000, 12, 12),
        ("1234567893", "0", "0450", "2024-02", 20, 12, 12),
        ("1234567893", "1234567890", "A12!4", "2024-03", 20, 12, 12),
    ])
    con.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(source)])
    async def query(sql):
        cursor = con.execute(sql)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    monkeypatch.setattr(db, "query_async", query)
    monkeypatch.setattr(db, "get_parquet_path", lambda: source.as_posix())
    first = asyncio.run(dv.run_validation(3, sample_seed=7))
    second = asyncio.run(dv.run_validation(3, sample_seed=7))
    assert first["status"] == "complete"
    assert first["sample_sha256"] == second["sample_sha256"]
    assert first["sample_seed"] == 7
    assert first["sample_contract_version"] == "duckdb-typed-hash-v3"
    assert first["sample_engine_version"] == duckdb.__version__
    assert first["diagnostic_encoding_version"] == "typed-json-v1"
    assert first["servicing_identity_states"] == {"missing": 0, "placeholder": 2, "valid": 0, "malformed": 1}
    assert first["code_system_mismatch_records"] == 1
    assert first["invalid_records"] == 2
    assert first["review_flags"]["high_value_aggregate_exceeds_1m"] == 1
    assert "amount_exceeds_1m" not in first["failures"]
    assert len(first["diagnostic_examples_admin_only"]) == 3
    assert {item["raw_source_row"]["servicing_npi"] for item in first["diagnostic_examples_admin_only"]} == {"null", "0", "1234567890"}
    con.execute("SET threads=1")
    subset_a = asyncio.run(dv.run_validation(2, sample_seed=7))
    con.execute("SET threads=4")
    subset_b = asyncio.run(dv.run_validation(2, sample_seed=7))
    assert subset_a["sample_size"] == subset_b["sample_size"] == 2
    assert subset_a["sample_sha256"] == subset_b["sample_sha256"]
    assert first["diagnostic_snapshot_sha256"] == second["diagnostic_snapshot_sha256"]
    assert dv._sample_digest(first["diagnostic_examples_admin_only"]) == first["diagnostic_snapshot_sha256"]
    con.close()


def test_sample_digest_preserves_duplicates_but_ignores_return_order():
    rows = [_row(), _row(hcpcs_code="0450")]
    assert dv._sample_digest(rows) == dv._sample_digest(list(reversed(rows)))
    assert dv._sample_digest(rows) != dv._sample_digest(rows + [rows[0]])


def test_nonfinite_and_date_diagnostics_are_api_json_safe(monkeypatch):
    import asyncio
    import math
    from datetime import date
    from decimal import Decimal
    from fastapi.encoders import jsonable_encoder
    from starlette.responses import JSONResponse
    import data.duckdb_client as db
    fixtures = [_row(total_paid=value, total_claims=12, claim_from_month=date(2024, 1, 1))
                for value in (float("nan"), float("inf"), float("-inf"))]
    async def query(sql):
        if sql.startswith("DESCRIBE"):
            return [{"column_name": c, "column_type": "DOUBLE" if c.startswith("TOTAL_") else "VARCHAR"} for c in dv.EXPECTED_COLUMNS]
        return [{"cnt": 3}] if "COUNT(*)" in sql else fixtures
    monkeypatch.setattr(db, "query_async", query)
    monkeypatch.setattr(db, "get_parquet_path", lambda: "synthetic.parquet")
    result = asyncio.run(dv.run_validation(3))
    assert result["status"] == "complete" and result["invalid_records"] == 3
    # Exercise the endpoint's real serialization mechanism, not permissive
    # json.dumps defaults which would allow nonstandard NaN/Infinity tokens.
    response = JSONResponse(jsonable_encoder(result))
    assert response.status_code == 200
    diagnostics = result["diagnostic_examples_admin_only"]
    assert {item["raw_source_row"]["total_paid"]["source_value"] for item in diagnostics} == {"NaN", "Infinity", "-Infinity"}
    assert diagnostics[0]["raw_source_row"]["claim_from_month"] == {"source_type": "date", "source_value": "2024-01-01"}
    assert math.isnan(fixtures[0]["total_paid"])  # raw fixture never changed
    assert dv._diagnostic_value(Decimal("1.1234567890123456789")) == {"source_type": "Decimal", "source_value": "1.1234567890123456789"}
    assert dv._sample_digest([{"value": float("nan")}]) != dv._sample_digest([{"value": "NaN"}])
