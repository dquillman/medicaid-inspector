"""DOJ shortlist: most provable first, nothing stale, nothing already sent to DOJ."""
import datetime as dt

import pytest

from services import doj_shortlist as ds

TODAY = dt.date(2026, 10, 21)


@pytest.fixture
def sources(monkeypatch):
    import core.perse_store as perse
    import core.oig_tips_store as tips
    import core.review_store as rs
    import core.store as store
    import services.fraud_brain as fb

    leads = [
        {"npi": "1000000001", "kind": "medicare_revoked_billing", "provider_name": "OLD REVOKED",
         "specialty": "Hospice", "last_month": "2020-06", "paid_after_revocation": 900_000},
        {"npi": "1000000002", "kind": "deactivated_billing", "provider_name": "DEAD NPI",
         "specialty": "Internal Medicine", "last_month": "2024-12", "paid_after_deactivation": 50_000},
        {"npi": "1000000003", "kind": "medicare_revoked_billing", "provider_name": "HOSPICE REVOKED",
         "specialty": "Hospice", "last_month": "2024-11", "paid_after_revocation": 10_000},
        {"npi": "1000000004", "kind": "recovery_lead", "provider_name": "EXCLUDED LATER",
         "specialty": "Hospice", "last_month": "2024-12", "paid_after_exclusion": 0},
        {"npi": "1000000005", "kind": "active_exclusion", "provider_name": "SENT TO DOJ",
         "specialty": "Hospice", "last_month": "2024-12", "paid_after_exclusion": 5_000_000},
        {"npi": "1000000006", "kind": "deactivated_billing", "provider_name": "JUDGED NOT FRAUD",
         "specialty": "Hospice", "last_month": "2024-12", "paid_after_deactivation": 70_000},
    ]
    review = [
        {"npi": "1000000010", "queue_status": "tip_filed", "total_paid": 2_000_000},
        {"npi": "1000000011", "queue_status": "dismissed", "total_paid": 9_000_000},
    ]
    statuses = {"1000000010": "tip_filed", "1000000011": "dismissed", "1000000006": "dismissed"}
    brain = [{"npi": "1000000020", "brain_rank": 7, "brain_score": 61.0, "specialty": "Home Health",
              "total_paid": 3_000_000, "last_active_month": "2024-10"}]
    providers = {"1000000010": {"provider_name": "OIG CASE", "specialty": "Home Health",
                                "last_month": "2024-09"}}

    leads += [
        {"npi": "1000000007", "kind": "deactivated_window", "provider_name": "PAPERWORK LAPSE",
         "specialty": "Hospice", "last_month": "2024-12", "paid_during_deactivation": 9_000_000,
         "deactivation_date": "03/31/2022", "reactivation_date": "05/20/2022"},
        {"npi": "1000000012", "kind": "deactivated_window", "provider_name": "LONG GAP",
         "specialty": "Hospice", "last_month": "2024-12", "paid_during_deactivation": 400_000,
         "deactivation_date": "01/01/2022", "reactivation_date": "01/01/2023"},
        {"npi": "1000000008", "kind": "deactivated_billing", "provider_name": "Dead NPI, Inc.",
         "specialty": "Internal Medicine", "last_month": "2024-12", "paid_after_deactivation": 20_000},
        {"npi": "1000000009", "kind": "deactivated_billing", "provider_name": "ALREADY FILED CO",
         "specialty": "Hospice", "last_month": "2024-12", "paid_after_deactivation": 1_000},
    ]
    monkeypatch.setattr(perse, "list_leads", lambda limit=0, **k: {"leads": leads})
    monkeypatch.setattr(tips, "filed_npis", lambda dest="oig": {"1000000005"} if dest == "doj" else set())
    monkeypatch.setattr(tips, "list_tips", lambda: [
        {"npi": "1000000005", "destination": "doj", "provider_name": "SENT TO DOJ"},
        {"npi": "1999999999", "destination": "doj", "provider_name": "Already Filed Co."},
    ])
    monkeypatch.setattr(rs, "get_review_queue", lambda *a, **k: review)
    monkeypatch.setattr(rs, "get_queue_statuses", lambda npis: {n: statuses[n] for n in npis if n in statuses})
    monkeypatch.setattr(store, "get_provider_by_npi", lambda npi: providers.get(npi))
    monkeypatch.setattr(fb, "get_top_frauds", lambda *a, **k: {"top": brain})


def test_shortlist_order_and_filters(sources):
    out = ds.build_shortlist(TODAY)
    order = [(r["npi"], r["tier"]) for r in out["leads"]]
    assert order == [
        ("1000000010", 1),   # worked case (OIG tip) not yet sent to DOJ
        ("1000000003", 2),   # per-se, DOJ priority area (hospice) beats a bigger non-priority lead
        ("1000000012", 2),   # a year-long deactivation gap is a lead, not a lapse
        ("1000000002", 2),
        ("1000000020", 3),   # statistical Brain lead in a priority area
    ]
    assert "deactivated for about 12 months" in out["leads"][2]["caveat"]
    # 1000000008 ("Dead NPI, Inc.") merges into 1000000002 ("DEAD NPI"): one company.
    assert out["leads"][3]["related_npis"] == ["1000000008"]
    assert out["leads"][3]["amount"] == 70_000
    # A 50-day lapse never reaches the DOJ list; a company already filed with
    # DOJ under another NPI drops too.
    assert all(r["npi"] not in ("1000000007", "1000000009") for r in out["leads"])
    assert out["dropped"] == {"too_old": 1, "already_doj": 2, "closed": 1, "same_company": 1,
                              "short_lapse": 1, "unreliable_status": 0}
    assert out["cutoff_month"] == "2020-10"     # 6-year window (v3.63.0)
    assert all(r["npi"] != "1000000004" for r in out["leads"]), "recovery lead is not billing while barred"
    assert out["leads"][1]["doj_priority_area"] == "Hospice"
    assert out["leads"][1]["amount_label"].startswith("Payments from 2 months after the Medicare revocation")


def test_shortlist_endpoint_requires_auth(client):
    assert client.get("/api/doj/shortlist").status_code in (401, 403)


def test_older_leads_are_recoverable_via_explicit_filter(sources):
    default = ds.build_shortlist(TODAY)
    expanded = ds.build_shortlist(TODAY, include_older=True)
    assert default["age_filter"]["reversible"] is True
    assert all(r["npi"] != "1000000001" for r in default["leads"])
    old = next(r for r in expanded["leads"] if r["npi"] == "1000000001")
    assert old["timeliness_review_required"] is True
    assert old["timeliness_status"] == "older_evidence"
    assert "does not establish Medicaid" in old["program_scope_note"]
    assert expanded["dropped"]["too_old"] == 0


def test_older_exclusion_cases_stay_with_a_lawyer_caveat(sources, monkeypatch):
    """v3.63.0: We Care Transportation (excluded 2010, paid $4.44M 2018-2020) was
    silently dropped as 'too old'. Older exclusion cases now stay, flagged, and
    sort after the cases inside the 6-year window."""
    import core.perse_store as perse
    base = perse.list_leads()["leads"]
    extra = [
        {"npi": "1000000030", "kind": "active_exclusion", "provider_name": "WE CARE TRANSPORTATION",
         "specialty": "Transportation", "last_month": "2020-07", "paid_after_exclusion": 4_441_513},
        {"npi": "1000000031", "kind": "excluded_servicing", "provider_name": "ROOZBEH BADII",
         "specialty": "Internal Medicine", "last_month": "2021-12",
         "paid_as_servicing_after_exclusion": 44_839, "caveat": "Check the biller."},
        {"npi": "1000000032", "kind": "waived_exclusion", "provider_name": "WAIVED DOC",
         "specialty": "Oncology", "last_month": "2022-07", "paid_after_exclusion": 900_000},
    ]
    monkeypatch.setattr(perse, "list_leads", lambda limit=0, **k: {"leads": base + extra})
    out = ds.build_shortlist(TODAY)
    by = {r["npi"]: r for r in out["leads"]}
    old = by["1000000030"]
    assert old["timeliness_status"] == "older_evidence"
    assert "False Claims Act" in old["caveat"]
    assert old["amount"] == 4_441_513
    serv = by["1000000031"]
    assert serv["reason"].startswith("An excluded person provided or ordered services")
    assert serv["amount"] == 44_839 and serv["timeliness_status"] == "within_priority_window"
    assert "1000000032" not in by, "a waived exclusion is not a DOJ lead"
    order = [r["npi"] for r in out["leads"] if r["tier"] == 2]
    assert order.index("1000000031") < order.index("1000000030")   # in-window first
    # The old Medicare revocation (2020-06) is still dropped: only exclusions are kept.
    assert "1000000001" not in by
