"""
Missing-provider top-up — the Fraud Brain's "Add N missing" button.

The prescan walks providers in total_paid order with a persisted offset and
considers itself done when a batch comes back empty. Its stored provider count
was written when the dataset held 106,660 NPIs; it now holds 617,503. Two
populations fell through the gap, and this feature adds exactly those two —
not the whole 510k tail, which was measured and rejected.

What these tests protect: the SET logic. Scanning the wrong set is expensive
(it occupies prod's single instance) and scanning an already-cached NPI would
duplicate it in the cache.
"""
import asyncio
import sys
from unittest.mock import patch

import pytest

import services.scan_engine as se


def _cache(n: int) -> list[dict]:
    return [{"npi": f"1{i:09d}", "total_paid": 1000.0, "top_hcpcs": "T1019",
             "revenue_per_beneficiary": 10, "claims_per_beneficiary": 2}
            for i in range(n)]


class _FakePerse:
    """Stands in for core.perse_store."""
    leads: list[dict] = []

    @classmethod
    def list_leads(cls, **_kw):
        return {"leads": cls.leads}


import pathlib


def _run(cache, top_n, perse_leads, perse=None, artifact: pathlib.Path | None = None):
    """`from core import perse_store` resolves the ATTRIBUTE on the core package,
    so patching sys.modules does not intercept it — patch the attribute.

    The artifact path is redirected away from the developer's real
    missing_npis.json; pass `artifact` to point at a synthetic one. is_local is
    forced True so the live-query fallback stays reachable in tests."""
    import core
    _FakePerse.leads = perse_leads
    with patch.object(se, "get_prescanned", lambda: cache), \
         patch.object(se, "query_async",
                      lambda *a, **k: asyncio.sleep(0, result=top_n)), \
         patch.object(se, "_MISSING_ARTIFACT",
                      artifact or pathlib.Path("does-not-exist-missing.json")), \
         patch.object(se, "is_local", lambda: True), \
         patch.object(core, "perse_store", perse if perse is not None else _FakePerse):
        return asyncio.run(se.compute_missing_npis())


def test_finds_the_rank_gap():
    """Providers inside today's top-N by spend that were never scanned."""
    r = _run(_cache(3), [{"npi": "1000000000"}, {"npi": "2222222222"}, {"npi": "2333333333"}], [])
    assert r["rank_gap"] == ["2222222222", "2333333333"]
    assert r["npis"] == ["2222222222", "2333333333"]


def test_includes_perse_leads_below_the_cutoff():
    """Per-se leads are added even though they rank nowhere near the top-N —
    that is the entire point: they are provable regardless of dollar size."""
    r = _run(_cache(3), [{"npi": f"1{i:09d}"} for i in range(3)],
             [{"npi": "2444444444", "in_scan_cache": False}])
    assert r["rank_gap"] == []
    assert r["perse"] == ["2444444444"]
    assert r["npis"] == ["2444444444"]


def test_never_rescans_an_already_cached_provider():
    """A duplicate append would double-count the provider in the cache."""
    r = _run(_cache(3), [{"npi": "1000000000"}, {"npi": "1000000001"}],
             [{"npi": "1000000002", "in_scan_cache": True}])
    assert r["npis"] == []


def test_dedupes_a_provider_that_is_in_both_sources():
    """A big per-se lead can appear in the rank gap too — scan it once."""
    r = _run(_cache(2), [{"npi": "2222222222"}, {"npi": "1000000000"}],
             [{"npi": "2222222222", "in_scan_cache": False}])
    assert r["npis"].count("2222222222") == 1
    assert r["npis"] == ["2222222222"]


def test_a_missing_sweep_does_not_block_the_rank_gap():
    """perse_leads.json is optional. If the store blows up, the rank gap must
    still work rather than the whole top-up failing."""
    class _Broken:
        @staticmethod
        def list_leads(**_kw):
            raise RuntimeError("no sweep on disk")

    r = _run(_cache(2), [{"npi": "2222222222"}], [], perse=_Broken)
    assert r["rank_gap"] == ["2222222222"]
    assert r["perse"] == []
    assert r["npis"] == ["2222222222"]


def test_empty_cache_is_reported_not_crashed():
    """With no cache there is no top-N to diff against — say so."""
    r = _run([], [], [])
    assert r["npis"] == []
    assert "empty" in (r.get("note") or "").lower()


def test_artifact_is_preferred_and_rechecked_against_the_live_cache(tmp_path):
    """Prod cannot run the live diff (the remote-parquet query 503'd — that is
    why the artifact exists). The artifact must be used when present, and every
    NPI re-checked against the CURRENT cache so a stale artifact over-lists but
    never double-scans."""
    import json
    art = tmp_path / "missing_npis.json"
    art.write_text(json.dumps({
        "rank_gap": ["2222222222", "1000000000"],   # second one is now cached
        "perse": ["2444444444"],
    }), encoding="utf-8")
    r = _run(_cache(3), [], [], artifact=art)   # top_n empty: query must NOT be needed
    assert r["rank_gap"] == ["2222222222"]
    assert r["perse"] == ["2444444444"]
    assert r["npis"] == ["2222222222", "2444444444"]


def test_remote_deployment_without_artifact_says_so_instead_of_querying():
    """On the remote dataset the live diff is the thing that 503'd. With no
    artifact it must return an explanation, not attempt the query."""
    import core

    async def _boom(*a, **k):
        raise AssertionError("live diff must not run on a remote deployment")

    with patch.object(se, "get_prescanned", lambda: _cache(2)), \
         patch.object(se, "query_async", _boom), \
         patch.object(se, "_MISSING_ARTIFACT", pathlib.Path("absent-missing.json")), \
         patch.object(se, "is_local", lambda: False), \
         patch.object(core, "perse_store", _FakePerse):
        r = asyncio.run(se.compute_missing_npis())
    assert r["npis"] == []
    assert "artifact" in (r.get("note") or "").lower()


def test_preview_endpoint_requires_auth(client):
    assert client.get("/api/prescan/missing").status_code in (401, 403)
    assert client.post("/api/prescan/scan-missing").status_code in (401, 403)


def test_scan_missing_409s_while_another_scan_runs(client, auth_headers):
    with patch("main.is_scan_active", lambda: True):
        r = client.post("/api/prescan/scan-missing", headers=auth_headers)
    assert r.status_code == 409


def test_brain_cache_invalidation_actually_clears():
    """The button is worthless if the board keeps serving a 15-minute-old cache
    that predates the providers just added."""
    from services import fraud_brain
    fraud_brain._cache["result"] = {"top": [], "providers_evaluated": 1}
    fraud_brain._cache["computed_at"] = 9_999_999_999.0
    fraud_brain.invalidate_cache()
    assert fraud_brain._cache["result"] is None
    assert fraud_brain._cache["computed_at"] == 0.0
