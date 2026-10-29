"""v3.63.0: waiver-aware exclusion checks and the excluded-SERVICING signal.

Each case mirrors a real public-data finding from 2026-10-29 (see MFIBugs.md)."""
from services import perse_rules as R

EXCL = {"excl_date": "20180920", "excl_type": "1128b5", "name": "ROOZBEH BADII",
        "specialty": "INTERNAL MEDICINE", "general": "MEDICAL PRACTICE, MD",
        "waiver_date": "0", "waiver_state": ""}


def test_billing_exclusion_counts_only_whole_months_after():
    months = [(201809, 1000.0), (201810, 250.0), (201811, 50.0)]
    out = R.classify_billing_exclusion(EXCL, months)
    assert out["kind"] == "active_exclusion"
    assert out["paid_after_exclusion"] == 300.0          # Sept 2018 itself does not count


def test_billing_before_exclusion_is_a_recovery_lead():
    out = R.classify_billing_exclusion(EXCL, [(201801, 5000.0)])
    assert out["kind"] == "recovery_lead" and out["paid_after_exclusion"] == 0


def test_rescinded_waiver_still_counts():
    # Aswad (NM): waiver date 0 because the waiver was rescinded, state kept.
    aswad = {**EXCL, "excl_date": "20160120", "waiver_date": "0", "waiver_state": "NM"}
    out = R.classify_billing_exclusion(aswad, [(201801, 10_000.0), (202207, 5_000.0)])
    assert out["kind"] == "waived_exclusion"
    assert out["waiver_state"] == "NM"
    assert "waived this exclusion for NM" in out["caveat"]
    assert out["paid_after_exclusion"] == 15_000.0


def test_waiver_date_without_state():
    assert R.waiver_state({"waiver_date": "20150618", "waiver_state": ""}) == "an unknown state"
    assert R.waiver_state({"waiver_date": "0", "waiver_state": ""}) is None


def test_servicing_finding_splits_by_biller_after_exclusion():
    rows = [("1861845802", 201808, 9_999.0, 0.0),       # before: ignored
            ("1861845802", 202010, 20_000.0, 0.0),
            ("1205410933", 202105, 8_637.0, 0.0),
            ("1861845802", 202112, 16_202.0, 0.0)]
    f = R.servicing_finding(EXCL, rows)
    assert f["kind"] == "excluded_servicing"
    assert f["paid_as_servicing_after_exclusion"] == 44_839.0
    assert f["billers"][0] == {"npi": "1861845802", "paid": 36_202.0}
    assert f["top_biller_npi"] == "1861845802"
    assert f["servicing_months_after_exclusion"] == 3
    assert f["first_servicing_month_after"] == "2020-10" and f["last_servicing_month"] == "2021-12"
    assert "same-name" in f["caveat"]
    assert "1001.1901(b)" in f["citation"]


def test_servicing_nothing_after_exclusion_is_none():
    assert R.servicing_finding(EXCL, [("1", 201801, 100.0, 0.0)]) is None


def test_aide_on_drug_claims_gets_the_strong_same_name_caveat():
    # Ebony R. Gibson: excluded aide whose NPI sat on nurse medication claims.
    aide = {**EXCL, "excl_date": "20221120", "name": "EBONY GIBSON", "specialty": "HEALTH CARE AIDE",
            "general": "IND- LIC HC SERV PRO"}
    f = R.servicing_finding(aide, [("1659769446", 202212, 90_000.0, 80_000.0),
                                   ("1659769446", 202301, 21_473.0, 20_000.0)])
    assert "same-name mix-up" in f["caveat"]


def test_excluded_facility_gets_the_successor_caveat():
    hosp = {**EXCL, "excl_date": "20210420", "busname": "HEALTHSMART PACIFIC, INC", "name": "",
            "specialty": "HOSPITAL"}
    f = R.servicing_finding(hosp, [("1699703827", 202105, 1_000.0, 0.0)])
    assert "new owner at the same address" in f["caveat"]
    assert "same-name" not in f["caveat"]


def test_waived_servicing_is_not_an_active_finding():
    w = {**EXCL, "waiver_state": "IN"}
    f = R.servicing_finding(w, [("1497759260", 202406, 52_524.0, 0.0)])
    assert f["kind"] == "waived_exclusion"
