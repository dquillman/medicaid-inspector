"""
Per-se fraud sweep — the leads that live BELOW the $1M prescan cutoff.

The point of these tests is the coverage claim: an OIG-excluded provider or a
dead NPI that bills is referable at ANY dollar amount, so the sweep must serve
leads that are not in the scan cache at all, and must never present a
billed-before-exclusion recovery lead as active fraud.
"""
import json

import pytest

from core import perse_store


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    """Write a synthetic sweep and point the store at it.

    Deliberately mixes a lead INSIDE the scan cache with two OUTSIDE it — the
    outside ones are the whole reason this feature exists.

    Also sets the LIVE scan cache to match, because in_scan_cache is resolved
    against core.store rather than read from the file (the stored value is a
    build-time snapshot that goes stale as soon as a top-up runs).
    """
    import core.store as _store
    monkeypatch.setattr(_store, "prescanned_providers", [{"npi": "1111111111"}])
    payload = {
        "generated_at": "2026-07-26T00:00:00Z",
        "scanned_npis": 106660,
        "summary": {
            "active_exclusion": {"count": 2, "total_paid": 1_500_000.0,
                                 "outside_scan_cache": 1, "outside_scan_cache_paid": 500_000.0},
            "recovery_lead": {"count": 1, "total_paid": 250_000.0,
                              "outside_scan_cache": 1, "outside_scan_cache_paid": 250_000.0},
        },
        "leads": [
            {"npi": "1111111111", "kind": "active_exclusion", "provider_name": "BIG BILLER",
             "state": "TX", "total_paid": 1_000_000.0, "paid_after_exclusion": 1_000_000.0,
             "exclusion_date": "20150101", "in_scan_cache": True},
            {"npi": "2222222222", "kind": "active_exclusion", "provider_name": "SMALL BILLER",
             "state": "NM", "total_paid": 500_000.0, "paid_after_exclusion": 500_000.0,
             "exclusion_date": "20160101", "in_scan_cache": False},
            {"npi": "3333333333", "kind": "recovery_lead", "provider_name": "EXCLUDED LATER",
             "state": "KS", "total_paid": 250_000.0, "paid_after_exclusion": 0.0,
             "exclusion_date": "20250101", "in_scan_cache": False},
        ],
    }
    path = tmp_path / "perse_leads.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(perse_store, "_PATH", path)
    perse_store.reload()
    yield payload
    monkeypatch.setattr(perse_store, "_PATH", tmp_path / "does-not-exist.json")
    perse_store.reload()


def test_sweep_surfaces_leads_below_the_scan_cutoff(client, auth_headers, sweep):
    """The reason this exists: two of three leads are invisible to the prescan."""
    r = client.get("/api/perse?outside_scan_cache=true", headers=auth_headers)
    assert r.status_code == 200
    npis = [x["npi"] for x in r.json()["leads"]]
    assert npis == ["2222222222", "3333333333"]


def test_recovery_lead_is_not_reported_as_active_fraud(client, auth_headers, sweep):
    """Billing that PREDATES an exclusion is a clawback, not billing-while-barred.
    Conflating the two would put a false accusation in a federal referral."""
    r = client.get("/api/perse?kind=active_exclusion", headers=auth_headers)
    assert r.status_code == 200
    kinds = {x["kind"] for x in r.json()["leads"]}
    assert kinds == {"active_exclusion"}
    assert all(x["paid_after_exclusion"] > 0 for x in r.json()["leads"])


def test_in_scan_cache_is_resolved_live_not_read_from_the_file(sweep, monkeypatch):
    """The stored in_scan_cache is a BUILD-TIME snapshot. After the 2026-07-27
    top-up scanned those providers, the board still announced "379 leads the
    risk model can't see" and the table still badged them UNSCANNED — while all
    379 were in the cache with risk scores. Resolve it against the live cache."""
    import core.store as store

    # The sweep fixture marks 2222222222 and 3333333333 as NOT cached.
    # Put one of them in the live cache and it must flip.
    monkeypatch.setattr(store, "prescanned_providers",
                        [{"npi": "1111111111"}, {"npi": "2222222222"}])

    rows = {r["npi"]: r for r in perse_store.list_leads(limit=100)["leads"]}
    assert rows["2222222222"]["in_scan_cache"] is True, "stale flag served"
    assert rows["3333333333"]["in_scan_cache"] is False, "genuinely unscanned lead lost"

    # The filter must agree with the live state, not the file.
    only_unseen = perse_store.list_leads(outside_scan_cache=True, limit=100)
    assert [r["npi"] for r in only_unseen["leads"]] == ["3333333333"]

    # And the per-kind summary must be recomputed, not read from the file block.
    assert perse_store.get_summary()["by_kind"]["active_exclusion"]["outside_scan_cache"] == 0

    # Single-lead lookup (provider-page badge) too.
    assert perse_store.get_lead("2222222222")["in_scan_cache"] is True


def test_summary_reports_how_many_leads_the_model_cannot_see(client, auth_headers, sweep):
    r = client.get("/api/perse/summary", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["total_leads"] == 3
    assert body["by_kind"]["active_exclusion"]["outside_scan_cache"] == 1


def test_lead_lookup_for_one_npi(client, auth_headers, sweep):
    r = client.get("/api/perse/2222222222", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["has_lead"] is True
    assert r.json()["label"] == "Billing while excluded"

    r = client.get("/api/perse/9999999999", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["has_lead"] is False


def test_bad_kind_and_bad_npi_are_rejected(client, auth_headers, sweep):
    assert client.get("/api/perse?kind=nonsense", headers=auth_headers).status_code == 400
    assert client.get("/api/perse/abc", headers=auth_headers).status_code == 400


def test_perse_requires_auth(client, sweep):
    assert client.get("/api/perse").status_code in (401, 403)
    assert client.get("/api/perse/summary").status_code in (401, 403)


def test_excluded_page_serves_the_full_universe_sweep(client, auth_headers, sweep):
    """/exclusions/excluded must read the sweep, not just the scan cache."""
    r = client.get("/api/exclusions/excluded", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "perse_sweep"
    assert body["total"] == 3
    assert any(p["in_scan_cache"] is False for p in body["providers"])


def test_brain_counts_only_PROVABLE_unworked_leads(sweep):
    """The board's banner must not overstate. recovery_lead (billing that
    predates the exclusion) is a clawback, not billing-while-barred, so it is
    counted separately — never behind the 'provable' number."""
    from services.fraud_brain import _perse_waiting_summary
    s = _perse_waiting_summary()
    assert s["available"] is True
    assert s["provable"] == 2          # the two active_exclusion rows
    assert s["recovery"] == 1          # counted, but kept out of 'provable'
    assert s["below_cutoff"] == 1      # only the out-of-cache provable one
    assert s["paid_while_barred"] == 1_500_000.0


def test_brain_banner_hides_itself_without_a_sweep(tmp_path, monkeypatch):
    from services.fraud_brain import _perse_waiting_summary
    monkeypatch.setattr(perse_store, "_PATH", tmp_path / "absent.json")
    perse_store.reload()
    assert _perse_waiting_summary() == {
        "available": False, "provable": 0, "recovery": 0, "below_cutoff": 0}


def test_excluded_page_falls_back_when_no_sweep_exists(client, auth_headers, tmp_path, monkeypatch):
    """A fresh checkout has no sweep — the page must still work and must SAY
    that its coverage is limited rather than silently under-reporting."""
    monkeypatch.setattr(perse_store, "_PATH", tmp_path / "absent.json")
    perse_store.reload()
    r = client.get("/api/exclusions/excluded", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "prescan_only"
    assert "full billing universe" in (body["universe_note"] or "")
