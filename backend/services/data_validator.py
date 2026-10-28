"""
Data validation for Medicaid claims data.
Validates NPI format (Luhn check), claim amounts, dates, and reports failures.
Runs as part of scan startup and provides a data quality summary endpoint.
"""
import time
import math
import logging
import hashlib
import json
import re
from typing import Optional
from datetime import datetime, date
from decimal import Decimal

log = logging.getLogger(__name__)

# In-memory validation results (latest run)
_validation_result: dict = {
    "last_run": None,
    "status": "never_run",
    "total_records": 0,
    "valid_records": 0,
    "failures": {},
    "summary": {},
}


def _luhn_check(npi: str) -> bool:
    """
    Validate NPI using the Luhn algorithm (mod-10 check).
    NPIs are 10 digits; the check digit is the last digit.
    Per CMS, prefix with '80840' before applying Luhn to the full 15-digit number.
    """
    if not npi or len(npi) != 10 or any(ch not in "0123456789" for ch in npi):
        return False
    # NPI Luhn: prefix with '80840', then standard Luhn on all 15 digits
    full = "80840" + npi
    total = 0
    for i, ch in enumerate(reversed(full)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_npi(npi_str: str) -> dict:
    """Validate a single NPI. Returns dict with is_valid and failure reasons."""
    issues = []
    if not npi_str:
        issues.append("empty_npi")
    elif not str(npi_str).isdigit():
        issues.append("non_numeric_npi")
    elif len(str(npi_str)) != 10:
        issues.append("wrong_length_npi")
    elif not _luhn_check(str(npi_str)):
        issues.append("luhn_check_failed")
    return {"npi": npi_str, "valid": len(issues) == 0, "issues": issues}


def validate_claim_amount(amount: float, field_name: str = "amount") -> list[str]:
    """Validate a claim amount. Returns list of issues (empty = valid)."""
    issues = []
    if amount is None:
        return [f"{field_name}_missing"]
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return [f"{field_name}_not_numeric"]
    if not math.isfinite(val):
        return [f"{field_name}_not_finite"]
    if val < 0:
        issues.append(f"{field_name}_negative")
    if val > 1_000_000:
        issues.append(f"{field_name}_exceeds_1m")
    return issues


def validate_date(date_val, field_name: str = "date") -> list[str]:
    """Validate a date value. Returns list of issues (empty = valid)."""
    issues = []
    if date_val is None:
        return issues
    try:
        if isinstance(date_val, str):
            # Try common formats
            for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%Y%m"):
                try:
                    dt = datetime.strptime(date_val, fmt)
                    break
                except ValueError:
                    continue
            else:
                issues.append(f"{field_name}_unparseable")
                return issues
        elif isinstance(date_val, (int, float)):
            # Could be a month number like 202301 or a timestamp
            s = str(int(date_val))
            if len(s) == 6:  # YYYYMM format
                dt = datetime(int(s[:4]), int(s[4:6]), 1)
            elif len(s) == 8:  # YYYYMMDD format
                dt = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
            else:
                issues.append(f"{field_name}_unknown_format")
                return issues
        else:
            dt = date_val

        now = datetime.now()
        if hasattr(dt, 'year'):
            if dt.year < 2010:
                issues.append(f"{field_name}_before_2010")
            if dt > now:
                issues.append(f"{field_name}_in_future")
    except Exception:
        issues.append(f"{field_name}_validation_error")
    return issues


# The columns every query in this app assumes exist (data/duckdb_client.py,
# services/scan_engine.py, services/risk_scorer.py). A silently missing or
# renamed column doesn't raise — DuckDB would error loudly on an unknown
# column name in a SELECT, but a column that's merely EMPTY/all-null, or a
# new unexpected extra column, passes silently today. This check is cheap
# (a DESCRIBE reads only parquet metadata, not row data) so it can run
# unconditionally — unlike run_validation() below, which samples actual rows
# and is gated to local data only (see its own docstring for why).
EXPECTED_COLUMNS = {
    "BILLING_PROVIDER_NPI_NUM", "SERVICING_PROVIDER_NPI_NUM", "HCPCS_CODE", "CLAIM_FROM_MONTH",
    "TOTAL_PAID", "TOTAL_CLAIMS", "TOTAL_UNIQUE_BENEFICIARIES",
}

def schema_type_issues(rows: list[dict]) -> dict:
    """Validate storage contracts; numeric identifiers remain accepted without coercion."""
    identifiers = {"BILLING_PROVIDER_NPI_NUM", "SERVICING_PROVIDER_NPI_NUM"}
    counts = {"TOTAL_CLAIMS", "TOTAL_UNIQUE_BENEFICIARIES"}
    integer_types = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"}
    text_types = {"VARCHAR", "CHAR", "TEXT", "STRING"}
    numeric_types = integer_types | {"DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC"}
    issues = {}
    for row in rows:
        column = row.get("column_name")
        if column not in EXPECTED_COLUMNS:
            continue
        dtype = str(row.get("column_type") or "").upper().split("(")[0].strip()
        allowed = (integer_types | text_types) if column in identifiers else (
            numeric_types if column in counts or column == "TOTAL_PAID" else
            text_types | integer_types | {"DATE", "TIMESTAMP", "TIMESTAMP_NS", "TIMESTAMP WITH TIME ZONE"}
            if column == "CLAIM_FROM_MONTH" else text_types)
        if dtype not in allowed:
            issues[column] = {"actual_type": dtype or "unknown", "allowed_types": sorted(allowed)}
    return issues


def beneficiary_count_state(value) -> str:
    """Missing and explicit suppression are distinct; no numeric floor is inferred."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "missing"
    if isinstance(value, str) and value.strip().lower() in {"suppressed", "*", "<11", "< 11"}:
        return "suppressed"
    if isinstance(value, bool):
        return "invalid"
    try:
        number = float(value)
        if not math.isfinite(number) or number < 0 or not number.is_integer():
            return "invalid"
        return "zero" if number == 0 else "observed"
    except (TypeError, ValueError):
        return "invalid"


def servicing_identity_state(value) -> str:
    """Classify coverage without replacing the source value or inventing a join."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "missing"
    token = str(value).strip().lower()
    if token in {"none", "null", "nan", "n/a", "na", "unknown", "not available",
                 "not applicable", "not provided", "missing", "suppressed", "*", "-",
                 "0", "0.0", "0000000000", "9999999999", "-1", "-1.0"}:
        return "placeholder"
    return "valid" if validate_npi(str(value))["valid"] else "malformed"


def source_code_state(value) -> str:
    """Format classification only, never authoritative code-set membership."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "missing"
    if not isinstance(value, str):
        return "malformed"
    if re.fullmatch(r"[0-9]{4}", value):
        return "alternate_code_system_shape"
    return "hcpcs_format" if re.fullmatch(r"[A-Za-z0-9]{5}", value) else "malformed"


def _diagnostic_value(value):
    """Loss-aware JSON representation; nonfinite source numbers stay explicit.

    Never coerce NaN to missing, zero, or the string value a source actually
    supplied. Type-tag non-JSON values so diagnostics preserve that distinction.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"source_type": "float", "source_value": "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"}
    if isinstance(value, (datetime, date)):
        return {"source_type": type(value).__name__, "source_value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"source_type": "Decimal", "source_value": str(value)}
    if isinstance(value, bytes):
        return {"source_type": "bytes", "source_value_hex": value.hex()}
    if isinstance(value, dict):
        return {str(key): _diagnostic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_diagnostic_value(item) for item in value]
    return {"source_type": type(value).__name__, "source_value": str(value)}


def _sample_digest(rows: list[dict]) -> str:
    """Order-independent multiset fingerprint, preserving duplicate source rows."""
    encoded = sorted(json.dumps(_diagnostic_value(row), sort_keys=True, allow_nan=False, ensure_ascii=True,
                                separators=(",", ":")) for row in rows)
    return hashlib.sha256(("\n".join(encoded)).encode("utf-8")).hexdigest()


def source_record_contract(row: dict) -> dict:
    """Validate an aggregate source row, never a patient or clinical claim."""
    issues = []
    billing = row.get("npi")
    if billing is None or billing == "":
        issues.append("billing_identity_missing")
    elif not validate_npi(str(billing))["valid"]:
        issues.append("npi_invalid_identity")
    servicing = servicing_identity_state(row.get("servicing_npi"))
    if servicing == "malformed":
        issues.append("servicing_npi_invalid_identity")
    code = row.get("hcpcs_code")
    code_state = source_code_state(code)
    if code_state == "alternate_code_system_shape":
        issues.append("source_code_system_mismatch")
    elif code_state != "hcpcs_format":
        issues.append("invalid_hcpcs_code")
    month = row.get("claim_from_month")
    canonical_month = None
    if isinstance(month, datetime):
        canonical_month = month.strftime("%Y-%m") if month.day == 1 else None
    elif hasattr(month, "year") and hasattr(month, "month"):
        canonical_month = month.strftime("%Y-%m") if month.day == 1 else None
    elif isinstance(month, str) and re.fullmatch(r"\d{4}-\d{2}(?:-01)?", month):
        canonical_month = month[:7]
    elif isinstance(month, (int, str)) and re.fullmatch(r"\d{6}", str(month)):
        canonical_month = f"{str(month)[:4]}-{str(month)[4:]}"
    try:
        period = datetime.strptime(canonical_month, "%Y-%m")
        if not datetime(2018, 1, 1) <= period <= datetime(2024, 12, 1):
            issues.append("outside_published_coverage_period")
    except (TypeError, ValueError):
        canonical_month = None
        issues.append("invalid_source_month")
    state = beneficiary_count_state(row.get("total_unique_beneficiaries"))
    if state == "invalid":
        issues.append("invalid_beneficiary_count")
    key = None
    if canonical_month and code and row.get("npi"):
        key = (str(row["npi"]), ("" if row.get("servicing_npi") is None else str(row["servicing_npi"])), str(code).upper(), canonical_month)
    return {"issues": issues, "beneficiary_count_state": state,
            "servicing_identity_state": servicing,
            "servicing_identity_raw": row.get("servicing_npi"),
            "servicing_identity_join_eligible": servicing == "valid",
            "source_code_raw": code, "source_code_state": code_state,
            "hcpcs_inference_eligible": code_state == "hcpcs_format",
            "source_grain_key": key}


_schema_check_result: dict = {"last_run": None, "status": "never_run"}


async def check_schema() -> dict:
    """Cheap, unconditional (safe on remote data) schema-presence check.

    Returns explicit missing/unexpected-column state rather than letting an
    absent column silently read as all-null/zero everywhere downstream
    (audit 2026-10-24, item 6).
    """
    global _schema_check_result
    from data.duckdb_client import query_async, get_parquet_path
    src = get_parquet_path()
    try:
        rows = await query_async(f"DESCRIBE SELECT * FROM read_parquet('{src}') LIMIT 0")
        actual_columns = {r.get("column_name") for r in rows if r.get("column_name")}
        missing = sorted(EXPECTED_COLUMNS - actual_columns)
        unexpected = sorted(actual_columns - EXPECTED_COLUMNS)
        type_issues = schema_type_issues(rows)
        _schema_check_result = {
            "last_run": time.time(),
            "status": "missing_columns" if missing else "type_mismatch" if type_issues else "ok",
            "type_issues": type_issues,
            "missing_columns": missing,
            "unexpected_columns": unexpected,
            "actual_columns": sorted(actual_columns),
            "actual_types": {r["column_name"]: r.get("column_type") for r in rows if r.get("column_name")},
        }
    except Exception as exc:
        # Unknown must stay unknown, not silently "ok" — any downstream
        # reader of this result must treat status != "ok" as "do not trust
        # column-dependent computations without checking further."
        _schema_check_result = {
            "last_run": time.time(),
            "status": "error",
            "error": str(exc),
            "missing_columns": None,
            "unexpected_columns": None,
        }
        log.error("Schema check failed: %s", exc)
    return _schema_check_result


def get_schema_check_result() -> dict:
    return dict(_schema_check_result)


async def run_validation(sample_limit: int = 5000, sample_seed: int = 42) -> dict:
    """
    Run data validation against the active Parquet dataset.
    Samples up to `sample_limit` records for performance.
    Returns a validation summary.
    """
    global _validation_result
    from data.duckdb_client import query_async, get_parquet_path

    if isinstance(sample_limit, bool) or not isinstance(sample_limit, int) or not 1 <= sample_limit <= 100000:
        raise ValueError("sample_limit must be an integer from 1 to 100000")
    if isinstance(sample_seed, bool) or not isinstance(sample_seed, int) or not 0 <= sample_seed <= 2147483647:
        raise ValueError("sample_seed must be an integer from 0 to 2147483647")
    start_time = time.time()
    src = get_parquet_path()

    failure_counts: dict[str, int] = {
        "invalid_npi_format": 0,
        "npi_luhn_failed": 0,
        "negative_amount": 0,
        "amount_exceeds_1m": 0,
        "date_before_2010": 0,
        "date_in_future": 0,
        "date_unparseable": 0,
        "null_npi": 0,
        "null_amount": 0,
        "invalid_amount": 0,
        "null_date": 0,
        "invalid_count": 0,
    }

    examples: dict[str, list] = {}  # first 3 examples per failure type

    try:
        schema = await check_schema()
        if schema["status"] != "ok":
            raise ValueError(f"Source schema contract failed: {schema['status']}")
        # Get total row count
        count_rows = await query_async(f"SELECT COUNT(*) AS cnt FROM read_parquet('{src}')")
        total_rows = int(count_rows[0]["cnt"]) if count_rows else 0

        # Vectorized typed hash avoids JSON serialization/cryptographic hashing
        # of every source row. Hash semantics are engine-version-specific; record
        # the version and retain a strict SHA256 of the selected sample below.
        import duckdb
        # Sample records for validation
        sample_sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            SERVICING_PROVIDER_NPI_NUM AS servicing_npi,
            HCPCS_CODE AS hcpcs_code,
            TOTAL_UNIQUE_BENEFICIARIES AS total_unique_beneficiaries,
            TOTAL_PAID AS total_paid,
            TOTAL_CLAIMS AS total_claims,
            CLAIM_FROM_MONTH AS claim_from_month
        FROM read_parquet('{src}')
        ORDER BY hash({sample_seed}, BILLING_PROVIDER_NPI_NUM,
                      SERVICING_PROVIDER_NPI_NUM, HCPCS_CODE, CLAIM_FROM_MONTH,
                      TOTAL_PAID, TOTAL_CLAIMS, TOTAL_UNIQUE_BENEFICIARIES),
                 BILLING_PROVIDER_NPI_NUM NULLS FIRST,
                 SERVICING_PROVIDER_NPI_NUM NULLS FIRST, HCPCS_CODE NULLS FIRST,
                 CLAIM_FROM_MONTH NULLS FIRST, TOTAL_PAID NULLS FIRST,
                 TOTAL_CLAIMS NULLS FIRST, TOTAL_UNIQUE_BENEFICIARIES NULLS FIRST
        LIMIT {sample_limit}
        """
        rows = await query_async(sample_sql)
        sampled = len(rows)

        valid_count = 0
        states = {"missing": 0, "suppressed": 0, "invalid": 0, "zero": 0, "observed": 0}
        missing_servicing = 0
        servicing_states = {key: 0 for key in ("missing", "placeholder", "valid", "malformed")}
        code_states = {key: 0 for key in ("missing", "malformed", "alternate_code_system_shape", "hcpcs_format")}
        diagnostics = []
        seen_grain = set()
        duplicate_grain = 0
        for row in rows:
            row_valid = True
            contract = source_record_contract(row)
            states[contract["beneficiary_count_state"]] += 1
            missing_servicing += contract["servicing_identity_state"] == "missing"
            servicing_states[contract["servicing_identity_state"]] += 1
            code_states[contract["source_code_state"]] += 1
            for issue in contract["issues"]:
                failure_counts[issue] = failure_counts.get(issue, 0) + 1
                row_valid = False
            key = contract["source_grain_key"]
            if key is not None:
                if key in seen_grain:
                    duplicate_grain += 1
                    row_valid = False
                seen_grain.add(key)
            npi = str(row.get("npi") or "")

            # NPI validation
            if not npi or npi == "None":
                failure_counts["null_npi"] += 1
                row_valid = False
            elif not npi.isdigit() or len(npi) != 10:
                failure_counts["invalid_npi_format"] += 1
                row_valid = False
                if len(examples.get("invalid_npi_format", [])) < 3:
                    examples.setdefault("invalid_npi_format", []).append(npi)
            elif not _luhn_check(npi):
                failure_counts["npi_luhn_failed"] += 1
                row_valid = False
                if len(examples.get("npi_luhn_failed", [])) < 3:
                    examples.setdefault("npi_luhn_failed", []).append(npi)

            # Amount validation
            total_paid = row.get("total_paid")
            if total_paid is None:
                failure_counts["null_amount"] += 1
                row_valid = False
            else:
                try:
                    val = float(total_paid)
                    if not math.isfinite(val):
                        failure_counts["invalid_amount"] += 1
                        row_valid = False
                    if val < 0:
                        failure_counts["negative_amount"] += 1
                        row_valid = False
                    if val > 1_000_000:
                        failure_counts["amount_exceeds_1m"] += 1
                        # Not necessarily invalid — just flagged
                except (TypeError, ValueError):
                    failure_counts["invalid_amount"] += 1
                    row_valid = False

            count = row.get("total_claims")
            try:
                number = float(count)
                if not math.isfinite(number) or number < 0 or not number.is_integer():
                    raise ValueError("Invalid count")
            except (TypeError, ValueError):
                failure_counts["invalid_count"] += 1
                row_valid = False

            # Date validation
            claim_month = row.get("claim_from_month")
            if claim_month is None:
                failure_counts["null_date"] += 1
                row_valid = False
            if claim_month is not None:
                date_issues = validate_date(claim_month, "claim_from_month")
                for issue in date_issues:
                    if "before_2010" in issue:
                        failure_counts["date_before_2010"] += 1
                        row_valid = False
                    elif "future" in issue:
                        failure_counts["date_in_future"] += 1
                        row_valid = False
                    elif "unparseable" in issue or "unknown" in issue:
                        failure_counts["date_unparseable"] += 1
                        row_valid = False

            if row_valid:
                valid_count += 1
            # Admin-only diagnostic response retains exact sampled values and
            # stable row fingerprint. Never log these provider-bearing rows.
            diagnostic_reasons = list(contract["issues"])
            if contract["servicing_identity_state"] in ("missing", "placeholder"):
                diagnostic_reasons.append("servicing_identity_coverage_" + contract["servicing_identity_state"])
            if not row_valid and not diagnostic_reasons:
                diagnostic_reasons.append("other_structural_validation_failure")
            if diagnostic_reasons and len(diagnostics) < 100:
                diagnostics.append({"row_sha256": _sample_digest([row]), "raw_source_row": _diagnostic_value(row),
                                    "issues": diagnostic_reasons,
                                    "servicing_identity_join_eligible": contract["servicing_identity_join_eligible"],
                                    "hcpcs_inference_eligible": contract["hcpcs_inference_eligible"]})

        elapsed = round(time.time() - start_time, 2)

        # Calculate quality score (0-100)
        quality_score = round((valid_count / sampled * 100) if sampled > 0 else 0, 1)

        # Non-zero failures only
        active_failures = {k: v for k, v in failure_counts.items() if v > 0 and k != "amount_exceeds_1m"}

        _validation_result = {
            "last_run": time.time(),
            "elapsed_sec": elapsed,
            "status": "complete",
            "total_dataset_rows": total_rows,
            "sample_size": sampled,
            "valid_records": valid_count,
            "invalid_records": sampled - valid_count,
            "invalid_records_description": "Source-contract exceptions, including alternate code-system shapes; not proof of corrupt data or fraud",
            "code_system_mismatch_records": code_states["alternate_code_system_shape"],
            "review_flags": {"high_value_aggregate_exceeds_1m": failure_counts["amount_exceeds_1m"]},
            "quality_score": quality_score,
            "validation_scope": "sampled structural quality, not fraud accuracy or complete-dataset certification",
            "sample_selection": "Lowest seeded DuckDB typed-hash keys, original-field tie breaks; deterministic within recorded engine version, not independent outcome validation",
            "sample_seed": sample_seed,
            "sample_sha256": _sample_digest(rows),
            "sample_contract_version": "duckdb-typed-hash-v3",
            "sample_engine": "DuckDB",
            "sample_engine_version": duckdb.__version__,
            "diagnostic_encoding_version": "typed-json-v1",
            "diagnostic_examples_admin_only": diagnostics,
            "diagnostic_snapshot_sha256": _sample_digest(diagnostics),
            "diagnostic_examples_limit": 100,
            "diagnostic_value_encoding": "Non-JSON source types are tagged with source_type and source_value; nonfinite numbers are never missing or zero",
            "servicing_identity_states": servicing_states,
            "source_code_states": code_states,
            "code_inference_eligible_rows": code_states["hcpcs_format"],
            "servicing_join_eligible_rows": servicing_states["valid"],
            "source_schema": schema,
            "program": "Medicaid",
            "published_coverage_period": {"start": "2018-01", "end": "2024-12"},
            "beneficiary_count_states": states,
            "missing_servicing_identity_rows": missing_servicing,
            "duplicate_source_grain_rows_in_sample": duplicate_grain,
            "source_grain": ["billing_npi", "servicing_npi", "hcpcs_code", "month"],
            "limitations": ["Sample duplicates are repeated aggregate keys, not duplicate clinical claims.",
                            "A clean sample cannot certify full-dataset uniqueness or fraud accuracy.",
                            "Missing/suppressed counts are unavailable evidence, not zero or fraud.",
                            "Published coverage is a contract; upstream freshness requires separate provenance.",
                            "Four-digit numeric code shape may belong to another coding system; no authoritative membership is asserted and HCPCS inference is ineligible.",
                            "Missing/placeholder servicing identity is coverage loss, not a malformed provider or fraud finding.",
                            "Typed-hash selection scans source fields; reproducibility requires unchanged inputs, schema, seed and recorded DuckDB version. The selected-sample SHA256 detects drift.",
                            "Admin-only diagnostic examples are capped; they retain source values and are not public output."],
            "failures": active_failures,
            "failure_examples": examples,
            "summary": {
                "npi_issues": failure_counts["invalid_npi_format"] + failure_counts["npi_luhn_failed"] + failure_counts["null_npi"],
                "amount_issues": failure_counts["negative_amount"] + failure_counts["null_amount"],
                "unavailable_beneficiary_counts": states["missing"] + states["suppressed"],
                "date_issues": failure_counts["date_before_2010"] + failure_counts["date_in_future"] + failure_counts["date_unparseable"],
                "high_value_claims": failure_counts["amount_exceeds_1m"],
            },
        }

        log.info(
            "[data_validator] Validation complete: %d/%d valid (%.1f%%), %d failures in %.2fs",
            valid_count, sampled, quality_score, sampled - valid_count, elapsed,
        )

    except Exception as e:
        log.error("[data_validator] Validation failed: %s", e, exc_info=True)
        _validation_result = {
            "last_run": time.time(),
            "status": "error",
            "error": str(e),
            "total_dataset_rows": 0,
            "sample_size": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "quality_score": 0,
            "failures": {},
            "summary": {},
        }

    return _validation_result


def get_validation_result() -> dict:
    """Return the latest validation result."""
    return dict(_validation_result)
