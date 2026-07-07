"""
Ownership Chain Tracing Service.

Traces ownership connections between providers using free NPPES data
already in the prescan cache:

1. Authorized Official — the person legally authorized for the NPI entity.
   Multiple NPIs sharing the same authorized official = same owner.
2. Organization Name matching — entities with similar/identical org names.
3. Address clustering — multiple entities at the same physical address.
4. Phone/fax overlap — shared contact numbers across entities.

This catches:
- Hidden ownership networks (one person controlling many provider entities)
- Shell company structures (multiple NPIs, same authorized official, same address)
- Franchise fraud (one owner, multiple locations, coordinated billing)
"""
import logging
from collections import defaultdict
from typing import Optional

from core.store import get_prescanned, get_provider_by_npi

log = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    """Normalize a string for comparison."""
    return (s or "").strip().upper().replace(".", "").replace(",", "")


def official_name(nppes: dict | None) -> str:
    """Canonical authorized-official display name from an NPPES dict.

    The canonical shape produced by BOTH the prescan cache (backfill) and the
    live NPPES client is {"name": ..., "title": ...}. This previously read
    first_name/last_name — keys that never exist in that shape — so every
    shared-official comparison silently saw an empty string and matched nothing.
    Falls back to first_name/last_name defensively for any legacy record.
    """
    ao = (nppes or {}).get("authorized_official") or {}
    name = ao.get("name") or " ".join(
        filter(None, [ao.get("first_name", ""), ao.get("last_name", "")]))
    return (name or "").strip()


async def trace_ownership_network_async(npi: str) -> dict:
    """Async entry point used by the HTTP route and the MCP tool.

    Resolves the target's authorized-official from the SAME canonical source
    get_provider uses — the prescan cache, falling back to a live NPPES fetch
    when the cache lacks it (e.g. the slim Cloud Run cache) — so the ownership
    view and the provider-detail view can never disagree about the official.
    The heavy candidate scan then runs in a worker thread.
    """
    import asyncio

    cached = get_provider_by_npi(npi)
    target_nppes = (cached or {}).get("nppes") or {}
    if not official_name(target_nppes):
        try:
            from data.nppes_client import get_provider as _live_nppes
            live = await _live_nppes(npi)
            if live:
                target_nppes = live
        except Exception as e:  # noqa: BLE001 — degrade to cache-only, never crash
            log.warning("ownership live NPPES fallback failed for %s: %s", npi, e)
    return await asyncio.to_thread(trace_ownership_network, npi, target_nppes)


def trace_ownership_network(npi: str, target_nppes: dict | None = None) -> dict:
    """
    Trace the ownership chain for a specific provider.
    Returns all connected entities via authorized official, address, phone/fax.

    target_nppes, when provided, is the canonical NPPES for the target (already
    resolved cache->live by the async wrapper) so this matches get_provider.
    """
    provider = get_provider_by_npi(npi)
    if not provider and not target_nppes:
        return {"npi": npi, "found": False, "error": "Provider not found"}
    provider = provider or {"npi": npi}

    nppes = target_nppes if target_nppes is not None else (provider.get("nppes") or {})
    auth_official = nppes.get("authorized_official") or {}
    auth_name = _normalize(official_name(nppes))
    addr = nppes.get("address") or {}
    address_key = _normalize(f"{addr.get('address_1', '')} {addr.get('city', '')} {addr.get('state', '')}")
    phone = _normalize(nppes.get("phone") or "")
    fax = _normalize(nppes.get("fax") or "")

    providers = get_prescanned()

    # Find connected providers
    connections = {
        "by_auth_official": [],
        "by_address": [],
        "by_phone": [],
    }
    seen = {npi}
    candidates_total = 0
    candidates_with_official = 0

    for p in providers:
        p_npi = p.get("npi", "")
        if p_npi == npi or p_npi in seen:
            continue
        candidates_total += 1

        p_nppes = p.get("nppes") or {}
        p_auth_name = _normalize(official_name(p_nppes))
        if len(p_auth_name) > 3:
            candidates_with_official += 1
        p_addr = p_nppes.get("address") or {}
        p_address_key = _normalize(f"{p_addr.get('address_1', '')} {p_addr.get('city', '')} {p_addr.get('state', '')}")
        p_phone = _normalize(p_nppes.get("phone") or "")
        p_fax = _normalize(p_nppes.get("fax") or "")

        connected = False
        connection_types = []

        # Same authorized official
        if auth_name and len(auth_name) > 3 and auth_name == p_auth_name:
            connection_types.append("authorized_official")
            connected = True

        # Same address
        if address_key and len(address_key) > 10 and address_key == p_address_key:
            connection_types.append("address")
            connected = True

        # Same phone or fax
        if phone and len(phone) >= 10 and (phone == p_phone or phone == p_fax):
            connection_types.append("phone")
            connected = True
        if fax and len(fax) >= 10 and (fax == p_phone or fax == p_fax):
            connection_types.append("fax")
            connected = True

        if connected:
            seen.add(p_npi)
            entry = {
                "npi": p_npi,
                "provider_name": p_nppes.get("name") or p.get("provider_name") or "",
                "state": p_addr.get("state") or p.get("state") or "",
                "risk_score": p.get("risk_score", 0),
                "total_paid": p.get("total_paid", 0),
                "connection_types": connection_types,
            }
            for ct in connection_types:
                if ct == "authorized_official":
                    connections["by_auth_official"].append(entry)
                elif ct == "address":
                    connections["by_address"].append(entry)
                elif ct in ("phone", "fax"):
                    connections["by_phone"].append(entry)

    # Compute network risk
    all_connected = list({e["npi"] for lst in connections.values() for e in lst})
    total_network_paid = sum(
        (get_provider_by_npi(n) or {}).get("total_paid", 0) for n in all_connected
    ) + (provider.get("total_paid", 0))

    avg_risk = 0
    if all_connected:
        risk_scores = [
            (get_provider_by_npi(n) or {}).get("risk_score", 0) for n in all_connected
        ]
        avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0

    network_risk = "LOW"
    if len(all_connected) >= 5 or avg_risk >= 50:
        network_risk = "HIGH"
    elif len(all_connected) >= 3 or avg_risk >= 30:
        network_risk = "MEDIUM"

    result = {
        "npi": npi,
        "found": True,
        "provider_name": nppes.get("name") or provider.get("provider_name") or "",
        "authorized_official": {
            # Canonical display name — same value get_provider surfaces. Non-null
            # whenever the record has an official, which is the whole point.
            "name": official_name(nppes),
            "title": auth_official.get("title", ""),
        },
        "address": dict(addr),
        "connections": connections,
        "network_summary": {
            "total_connected_entities": len(all_connected),
            "total_network_paid": round(total_network_paid, 2),
            "avg_connected_risk_score": round(avg_risk, 1),
            "network_risk": network_risk,
            "connected_npis": all_connected,
            # Coverage so "0 connections" is never confused with "no data to
            # compare" — the slim Cloud Run cache strips authorized officials.
            "official_match_coverage": {
                "candidates_total": candidates_total,
                "candidates_with_official_data": candidates_with_official,
            },
        },
    }
    if auth_name and len(auth_name) > 3 and candidates_with_official == 0:
        result["data_quality_warning"] = (
            "This deployment's provider cache holds no authorized-official data "
            "to compare against (e.g. the slim Cloud Run cache), so shared-official "
            "ownership matches cannot be computed. Zero here means 'no data', not "
            "'no connections' — run against the full cache for shared-official links."
        )
    return result


def find_ownership_clusters(min_size: int = 2, limit: int = 50) -> dict:
    """
    Scan all providers to find ownership clusters — groups of providers
    sharing the same authorized official.
    """
    providers = get_prescanned()
    if not providers:
        return {"clusters": [], "total_clusters": 0}

    # Group by authorized official
    auth_groups: dict[str, list[dict]] = defaultdict(list)

    for p in providers:
        nppes = p.get("nppes") or {}
        auth_name = _normalize(official_name(nppes))

        if not auth_name or len(auth_name) <= 3:
            continue

        addr = nppes.get("address") or {}
        auth_groups[auth_name].append({
            "npi": p["npi"],
            "provider_name": nppes.get("name") or p.get("provider_name") or "",
            "state": addr.get("state") or p.get("state") or "",
            "city": addr.get("city") or "",
            "risk_score": p.get("risk_score", 0),
            "total_paid": p.get("total_paid", 0),
            "total_claims": p.get("total_claims", 0),
        })

    # Filter to clusters meeting minimum size
    clusters = []
    for auth_name, members in auth_groups.items():
        if len(members) < min_size:
            continue

        total_paid = sum(m["total_paid"] for m in members)
        avg_risk = sum(m["risk_score"] for m in members) / len(members) if members else 0
        states = list(set(m["state"] for m in members if m["state"]))

        clusters.append({
            "authorized_official": auth_name,
            "entity_count": len(members),
            "total_paid": round(total_paid, 2),
            "avg_risk_score": round(avg_risk, 1),
            "max_risk_score": max(m["risk_score"] for m in members),
            "states": states,
            "multi_state": len(states) > 1,
            "members": sorted(members, key=lambda x: x["risk_score"], reverse=True),
        })

    clusters.sort(key=lambda x: (x["entity_count"], x["total_paid"]), reverse=True)
    clusters = clusters[:limit]

    return {
        "clusters": clusters,
        "total_clusters": len(clusters),
        "note": "Provider groups sharing the same authorized official — potential common ownership",
    }
