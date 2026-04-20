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


def trace_ownership_network(npi: str) -> dict:
    """
    Trace the ownership chain for a specific provider.
    Returns all connected entities via authorized official, address, phone/fax.
    """
    provider = get_provider_by_npi(npi)
    if not provider:
        return {"npi": npi, "found": False, "error": "Provider not found"}

    nppes = provider.get("nppes") or {}
    auth_official = nppes.get("authorized_official") or {}
    auth_name = _normalize(f"{auth_official.get('first_name', '')} {auth_official.get('last_name', '')}")
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

    for p in providers:
        p_npi = p.get("npi", "")
        if p_npi == npi or p_npi in seen:
            continue

        p_nppes = p.get("nppes") or {}
        p_auth = p_nppes.get("authorized_official") or {}
        p_auth_name = _normalize(f"{p_auth.get('first_name', '')} {p_auth.get('last_name', '')}")
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

    return {
        "npi": npi,
        "found": True,
        "provider_name": nppes.get("name") or provider.get("provider_name") or "",
        "authorized_official": {
            "name": auth_name,
            "first_name": auth_official.get("first_name", ""),
            "last_name": auth_official.get("last_name", ""),
            "title": auth_official.get("title", ""),
            "credential": auth_official.get("credential", ""),
        },
        "address": dict(addr),
        "connections": connections,
        "network_summary": {
            "total_connected_entities": len(all_connected),
            "total_network_paid": round(total_network_paid, 2),
            "avg_connected_risk_score": round(avg_risk, 1),
            "network_risk": network_risk,
            "connected_npis": all_connected,
        },
    }


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
        auth = nppes.get("authorized_official") or {}
        auth_name = _normalize(f"{auth.get('first_name', '')} {auth.get('last_name', '')}")

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
