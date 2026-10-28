"""NPI syntax/checksum eligibility; never an assertion of registry identity."""
import re


def is_valid_npi(value) -> bool:
    text = str(value) if value is not None else ""
    if not re.fullmatch(r"[0-9]{10}", text):
        return False
    digits = [int(char) for char in text]
    return (24 + sum((digit * 2 - (9 if digit >= 5 else 0)) if index % 2 == 0 else digit
                     for index, digit in enumerate(digits))) % 10 == 0


def valid_npi_sql(column: str) -> str:
    """Generate a safe DuckDB predicate for a trusted simple column name.

    TRY_CAST ensures invalid input cannot raise even if SQL evaluates checksum
    expressions before the regex filter. Prefix 80840 contributes 24 to Luhn.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", column):
        raise ValueError("Trusted SQL column identifier required")
    text = f"CAST({column} AS VARCHAR)"
    parts = []
    for index in range(10):
        digit = f"TRY_CAST(substr({text}, {index + 1}, 1) AS INTEGER)"
        parts.append(f"(2 * {digit} - CASE WHEN {digit} >= 5 THEN 9 ELSE 0 END)" if index % 2 == 0 else digit)
    return f"COALESCE((regexp_full_match({text}, '[0-9]{{10}}') AND ((24 + {' + '.join(parts)}) % 10 = 0)), FALSE)"
