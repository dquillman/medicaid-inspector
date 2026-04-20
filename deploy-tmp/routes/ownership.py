"""Ownership network analysis — group providers by authorized official."""
from fastapi import APIRouter, Depends
from core.store import get_prescanned
from routes.auth import require_admin

router = APIRouter(prefix="/api/ownership", tags=["ownership"], dependencies=[Depends(require_admin)])


@router.get("/networks")
async def get_ownership_networks():
    """Return all ownership networks with 3+ NPIs, sorted by total billing."""
    # Group by authorized official name (lowercased, trimmed)
    networks: dict[str, list[dict]] = {}

    for p in get_prescanned():
        nppes = p.get("nppes") or {}
        auth_off = nppes.get("authorized_official") or {}
        off_name = (auth_off.get("name") or "").strip()
        if not off_name:
            continue

        off_key = off_name.lower().strip()
        p_addr = nppes.get("address") or {}

        entry = {
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
        }
        networks.setdefault(off_key, []).append(entry)

    # Filter to 3+ NPIs and build response
    result = []
    for off_key, npis in networks.items():
        if len(npis) < 3:
            continue

        total_billing = sum(n["total_paid"] for n in npis)
        avg_risk = sum(n["risk_score"] for n in npis) / len(npis) if npis else 0
        top_risk = max(npis, key=lambda x: x["risk_score"])

        # Use original-cased name from first entry
        official_name = npis[0]["name"] if npis else off_key

        # Try to get the actual authorized official name (not provider name)
        for p in get_prescanned():
            p_nppes = p.get("nppes") or {}
            p_auth = p_nppes.get("authorized_official") or {}
            p_off = (p_auth.get("name") or "").strip()
            if p_off.lower().strip() == off_key:
                official_name = p_off
                break

        npis.sort(key=lambda x: x["risk_score"], reverse=True)

        result.append({
            "official_name": official_name,
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
