"""Test input validation helpers."""
import pytest
from fastapi import HTTPException


def test_validate_npi_valid():
    from routes.providers import _validate_npi
    assert _validate_npi("1234567890") == "1234567890"


def test_validate_npi_strips():
    from routes.providers import _validate_npi
    assert _validate_npi("  1234567890  ") == "1234567890"


def test_validate_npi_rejects_short():
    from routes.providers import _validate_npi
    with pytest.raises(HTTPException) as exc_info:
        _validate_npi("12345")
    assert exc_info.value.status_code == 400


def test_validate_npi_rejects_injection():
    from routes.providers import _validate_npi
    with pytest.raises(HTTPException):
        _validate_npi("1234' OR 1=1--")


def test_validate_hcpcs_valid():
    from routes.providers import _validate_hcpcs
    assert _validate_hcpcs("99213") == "99213"
    assert _validate_hcpcs("j0129") == "J0129"  # uppercased


def test_validate_hcpcs_rejects_injection():
    from routes.providers import _validate_hcpcs
    with pytest.raises(HTTPException):
        _validate_hcpcs("'; DROP TABLE--")


def test_validate_month_valid():
    from routes.providers import _validate_month
    assert _validate_month("2024-01") == "2024-01"


def test_validate_month_rejects_bad_format():
    from routes.providers import _validate_month
    with pytest.raises(HTTPException):
        _validate_month("January 2024")
