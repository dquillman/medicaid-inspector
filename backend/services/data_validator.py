"""
Data validation for Medicaid claims data.
Validates NPI format (Luhn check), claim amounts, dates, and reports failures.
Runs as part of scan startup and provides a data quality summary endpoint.
"""
import time
import logging
from typing import Optional
from datetime import datetime

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
    if not npi or len(npi) != 10 or not npi.isdigit():
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
        return issues  # null amounts are ok (optional fields)
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return [f"{field_name}_not_numeric"]
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


async def run_validation(sample_limit: int = 5000) -> dict:
    """
    Run data validation against the active Parquet dataset.
    Samples up to `sample_limit` records for performance.
    Returns a validation summary.
    """
    global _validation_result
    from data.duckdb_client import query_async, get_parquet_path

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
    }

    examples: dict[str, list] = {}  # first 3 examples per failure type

    try:
        # Get total row count
        count_rows = await query_async(f"SELECT COUNT(*) AS cnt FROM read_parquet('{src}')")
        total_rows = int(count_rows[0]["cnt"]) if count_rows else 0

        # Sample records for validation
        sample_sql = f"""
        SELECT
            BILLING_PROVIDER_NPI_NUM AS npi,
            TOTAL_PAID AS total_paid,
            TOTAL_CLAIMS AS total_claims,
            CLAIM_FROM_MONTH AS claim_from_month
        FROM read_parquet('{src}')
        USING SAMPLE {sample_limit}
        """
        rows = await query_async(sample_sql)
        sampled = len(rows)

        valid_count = 0
        for row in rows:
            row_valid = True
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
            else:
                try:
                    val = float(total_paid)
                    if val < 0:
                        failure_counts["negative_amount"] += 1
                        row_valid = False
                    if val > 1_000_000:
                        failure_counts["amount_exceeds_1m"] += 1
                        # Not necessarily invalid — just flagged
                except (TypeError, ValueError):
                    failure_counts["negative_amount"] += 1
                    row_valid = False

            # Date validation
            claim_month = row.get("claim_from_month")
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

            if row_valid:
                valid_count += 1

        elapsed = round(time.time() - start_time, 2)

        # Calculate quality score (0-100)
        quality_score = round((valid_count / sampled * 100) if sampled > 0 else 0, 1)

        # Non-zero failures only
        active_failures = {k: v for k, v in failure_counts.items() if v > 0}

        _validation_result = {
            "last_run": time.time(),
            "elapsed_sec": elapsed,
            "status": "complete",
            "total_dataset_rows": total_rows,
            "sample_size": sampled,
            "valid_records": valid_count,
            "invalid_records": sampled - valid_count,
            "quality_score": quality_score,
            "failures": active_failures,
            "failure_examples": examples,
            "summary": {
                "npi_issues": failure_counts["invalid_npi_format"] + failure_counts["npi_luhn_failed"] + failure_counts["null_npi"],
                "amount_issues": failure_counts["negative_amount"] + failure_counts["null_amount"],
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
