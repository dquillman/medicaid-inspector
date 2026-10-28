"""Administrative matches remain review leads without changing screening weights."""
from services.anomaly_detector import oig_excluded


def _match(monkeypatch):
    import core.oig_store as oig
    monkeypatch.setattr(oig, "is_excluded", lambda npi: (True, {"name": "SYNTHETIC", "excl_date": "20240620"}))


def test_same_month_match_does_not_establish_service_overlap(monkeypatch):
    _match(monkeypatch)
    result = oig_excluded("synthetic", {"last_month": "2024-06"})
    assert result["score"] == 1.0 and result["flagged"]
    assert "exact service-date overlap is unverified" in result["reason"]
    assert "per-se fraud" not in result["reason"]


def test_historical_exclusion_does_not_imply_recovery(monkeypatch):
    _match(monkeypatch)
    result = oig_excluded("synthetic", {"last_month": "2024-05"})
    assert result["score"] == 0.6 and result["flagged"]
    assert "does not establish" in result["reason"]
    assert "recovery lead" not in result["reason"]


def test_unknown_timing_remains_explicit(monkeypatch):
    _match(monkeypatch)
    result = oig_excluded("synthetic")
    assert result["score"] == 1.0
    assert "timing is unknown" in result["reason"]
