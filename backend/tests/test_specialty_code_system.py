from services.anomaly_detector import specialty_mismatch


def test_alternate_source_codes_do_not_become_specialty_allegations():
    provider = {"nppes": {"taxonomy": {"description": "Podiatrist"}}}
    result = specialty_mismatch(provider, [
        {"hcpcs_code": "99215", "total_paid": 100},
        {"hcpcs_code": "0450", "total_paid": 100000},
    ])
    assert not result["flagged"]
    assert result["score"] == 0
    assert "unavailable" in result["reason"]


def test_missing_source_code_withholds_specialty_inference():
    result = specialty_mismatch({}, [{"hcpcs_code": None, "total_paid": 100}])
    assert not result["flagged"]
    assert "unknown code system" in result["reason"]
