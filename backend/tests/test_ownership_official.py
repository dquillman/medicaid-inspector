"""
Regression tests for the authorized-official data-consistency bug.

Bug (fixed): the ownership tracer read `authorized_official.first_name/last_name`,
but the canonical NPPES shape — from both the prescan cache and the live NPPES
client — is `{"name", "title"}`. Every shared-official comparison therefore saw
an empty string and matched nothing, silently under-reporting ownership networks
(e.g. "Inspired Behavioral Health" showed 0 connections despite a populated
authorized official). These tests lock in the canonical shape, the two-endpoint
agreement, and the null case.
"""
import asyncio

import pytest

from services import ownership_tracer as OT
from services.ownership_tracer import (
    official_name,
    trace_ownership_network,
)

# Canonical NPPES shape (what the cache + live client actually produce).
INSPIRED = {
    "npi": "1111111111",
    "provider_name": "INSPIRED BEHAVIORAL HEALTH",
    "total_paid": 16_200_000,
    "risk_score": 45,
    "nppes": {
        "name": "INSPIRED BEHAVIORAL HEALTH",
        "authorized_official": {"name": "Brandy Leonhardt", "title": "CEO"},
        "address": {"address_1": "100 Main St", "city": "Austin", "state": "TX"},
    },
}
# A sibling entity controlled by the SAME official — the link that must surface.
SIBLING = {
    "npi": "2222222222",
    "provider_name": "SERENITY COUNSELING LLC",
    "total_paid": 900_000,
    "risk_score": 60,
    "nppes": {
        "name": "SERENITY COUNSELING LLC",
        "authorized_official": {"name": "Brandy Leonhardt", "title": "President"},
        "address": {"address_1": "999 Other Rd", "city": "Dallas", "state": "TX"},
    },
}
# An unrelated provider with a different official.
UNRELATED = {
    "npi": "3333333333",
    "provider_name": "UNRELATED CLINIC",
    "total_paid": 50_000,
    "risk_score": 10,
    "nppes": {
        "name": "UNRELATED CLINIC",
        "authorized_official": {"name": "Someone Else", "title": "Owner"},
        "address": {"address_1": "1 Elsewhere Ave", "city": "Houston", "state": "TX"},
    },
}
# Individual with no authorized official (legitimately null).
INDIVIDUAL = {
    "npi": "4444444444",
    "provider_name": "JANE SMITH MD",
    "total_paid": 5_000,
    "risk_score": 5,
    "nppes": {"name": "JANE SMITH MD", "authorized_official": None,
              "address": {"address_1": "5 Solo St", "city": "Waco", "state": "TX"}},
}


@pytest.fixture
def cache(monkeypatch):
    """Point the tracer at an in-memory fixture cache (no disk, no network)."""
    providers = [INSPIRED, SIBLING, UNRELATED, INDIVIDUAL]
    index = {p["npi"]: p for p in providers}
    monkeypatch.setattr(OT, "get_prescanned", lambda: providers)
    monkeypatch.setattr(OT, "get_provider_by_npi", lambda npi: index.get(npi))
    return index


def test_official_name_reads_canonical_shape():
    """The exact bug: {name,title} must yield the name, not empty string."""
    assert official_name(INSPIRED["nppes"]) == "Brandy Leonhardt"
    # legacy defensive shape still works
    assert official_name({"authorized_official": {"first_name": "A", "last_name": "B"}}) == "A B"
    # null official -> empty, no crash
    assert official_name(INDIVIDUAL["nppes"]) == ""
    assert official_name({}) == ""
    assert official_name(None) == ""


def test_shared_official_link_surfaces(cache):
    """The core detection pathway: a populated official yields a real match."""
    result = trace_ownership_network("1111111111")
    assert result["found"] is True
    # The official the tracer reports must be the same one get_provider surfaces.
    assert result["authorized_official"]["name"].upper() == "BRANDY LEONHARDT"
    by_official = [e["npi"] for e in result["connections"]["by_auth_official"]]
    assert "2222222222" in by_official, "sibling via shared official must be found"
    assert "3333333333" not in by_official, "different official must NOT match"
    assert result["network_summary"]["total_connected_entities"] >= 1


def test_get_provider_and_network_agree_on_official(cache):
    """Both endpoints must reflect the same populated official (non-null)."""
    # get_provider's canonical value for this NPI:
    gp_official = official_name(INSPIRED["nppes"])
    assert gp_official  # populated
    net = trace_ownership_network("1111111111")
    assert net["authorized_official"]["name"]  # non-null in the network view too
    assert net["authorized_official"]["name"].upper() == gp_official.upper()


def test_null_official_agrees_and_no_false_match(cache):
    """A provider with no official: both views agree it's empty, no bogus links."""
    result = trace_ownership_network("4444444444")
    assert result["found"] is True
    assert result["authorized_official"]["name"] == ""
    assert result["connections"]["by_auth_official"] == []


def test_coverage_reported_when_cache_lacks_officials(monkeypatch):
    """Slim-cache case: target has an official but candidates have none ->
    surface a data-quality warning instead of a silent '0 connections'."""
    slim_target = dict(INSPIRED)
    slim_sibling = {**SIBLING, "nppes": {"name": "SERENITY", "authorized_official": None}}
    providers = [slim_target, slim_sibling]
    index = {p["npi"]: p for p in providers}
    monkeypatch.setattr(OT, "get_prescanned", lambda: providers)
    monkeypatch.setattr(OT, "get_provider_by_npi", lambda npi: index.get(npi))

    result = trace_ownership_network("1111111111")
    cov = result["network_summary"]["official_match_coverage"]
    assert cov["candidates_total"] == 1
    assert cov["candidates_with_official_data"] == 0
    assert "data_quality_warning" in result


def test_async_wrapper_uses_live_fallback(monkeypatch):
    """When the cache lacks the target's official, the async wrapper backfills
    from the live NPPES client — so it agrees with get_provider's fallback."""
    cache_no_ao = {"npi": "1111111111", "provider_name": "INSPIRED", "nppes": {"name": "INSPIRED"}}
    monkeypatch.setattr(OT, "get_prescanned", lambda: [cache_no_ao])
    monkeypatch.setattr(OT, "get_provider_by_npi", lambda npi: cache_no_ao if npi == "1111111111" else None)

    async def fake_live(npi):
        return {"name": "INSPIRED BEHAVIORAL HEALTH",
                "authorized_official": {"name": "Brandy Leonhardt", "title": "CEO"}}

    import data.nppes_client as nc
    monkeypatch.setattr(nc, "get_provider", fake_live)

    result = asyncio.get_event_loop().run_until_complete(
        OT.trace_ownership_network_async("1111111111"))
    assert result["authorized_official"]["name"].upper() == "BRANDY LEONHARDT"
