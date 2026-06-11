"""Ownership network analysis — group providers by authorized official."""
import asyncio

from fastapi import APIRouter, Depends
from core.store import get_prescanned
from routes.auth import require_admin

router = APIRouter(prefix="/api/ownership", tags=["ownership"], dependencies=[Depends(require_admin)])


def compute_networks(providers: list[dict]) -> dict:
    """Group providers by authorized official; return networks with 3+ NPIs.

    Needs nppes.authorized_official on the providers, which only the FULL
    cache has — on the slim cache this returns zero networks (the route
    falls back to the precomputed section in that case).
    """
    networks: dict[str, list[dict]] = {}
    off_key_to_official: dict[str, str] = {}

    for p in providers:
        nppes = p.get("nppes") or {}
        auth_off = nppes.get("authorized_official") or {}
        off_name = (auth_off.get("name") or "").strip()
        if not off_name:
            continue

        off_key = off_name.lower().strip()
        off_key_to_official.setdefault(off_key, off_name)
        p_addr = nppes.get("address") or {}

        networks.setdefault(off_key, []).append({
            "npi": p["npi"],
            "name": p.get("provider_name") or nppes.get("name") or "",
            "entity_type": nppes.get("entity_type") or "",
            "risk_score": p.get("risk_score", 0),
            "total_paid": p.get("total_paid", 0),
            "flag_count": len(p.get("flags") or []),
            "specialty": (nppes.get("taxonomy") or {}).get("description") or "",
            "address": {
                "line1": p_addr.get("line1", ""),
                "city": p_addr.get("city", ""),
                "state": p_addr.get("state", ""),
                "zip": p_addr.get("zip", ""),
            },
        })

    result = []
    for off_key, npis in networks.items():
        if len(npis) < 3:
            continue

        total_billing = sum(n["total_paid"] for n in npis)
        avg_risk = sum(n["risk_score"] for n in npis) / len(npis) if npis else 0
        top_risk = max(npis, key=lambda x: x["risk_score"])

        npis.sort(key=lambda x: x["risk_score"], reverse=True)

        result.append({
            "official_name": off_key_to_official.get(off_key, off_key),
            "npi_count": len(npis),
            "total_billing": round(total_billing, 2),
            "avg_risk_score": round(avg_risk, 1),
            "top_risk_npi": {
                "npi": top_risk["npi"],
                "name": top_risk["name"],
                "risk_score": top_risk["risk_score"],
            },
            "npis": npis,
        })

    result.sort(key=lambda x: x["total_billing"], reverse=True)
    return {"networks": result, "total_networks": len(result)}


@router.get("/networks")
async def get_ownership_networks():
    """Return all ownership networks with 3+ NPIs, sorted by total billing."""
    live = await asyncio.to_thread(compute_networks, get_prescanned())
    if live["total_networks"] > 0:
        return live

    # Slim cache (Cloud Run) strips nppes.authorized_official, so the live
    # computation finds nothing — serve the workstation-precomputed networks.
    from services.precomputed_store import get_precomputed
    pre = get_precomputed("ownership_networks")
    if pre:
        return pre
    return {
        **live,
        "note": "Ownership networks need full NPPES data (not in the slim cache) "
                "and no precomputed copy is available — run the precompute script.",
    }
