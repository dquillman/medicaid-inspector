from fastapi import APIRouter, Depends
from core.config import settings
from core.store import get_prescanned
from routes.auth import require_user

router = APIRouter(prefix="/api/geography", tags=["geography"], dependencies=[Depends(require_user)])


def _get_provider_state(p: dict) -> str:
    return p.get("state") or p.get("nppes", {}).get("address", {}).get("state", "")


def _get_provider_city(p: dict) -> str:
    return p.get("city") or p.get("nppes", {}).get("address", {}).get("city", "")


def _get_provider_zip(p: dict) -> str:
    # Slim cache stores zip at top level; full cache has it in nppes.address
    return p.get("zip") or p.get("nppes", {}).get("address", {}).get("zip", "")


def _is_flagged(p: dict) -> bool:
    return p.get("risk_score", 0) > settings.RISK_THRESHOLD


@router.get("/by-zip")
async def geography_by_zip():
    """
    Aggregate providers by ZIP prefix (first 3 digits for privacy).
    Returns top 50 ZIPs by flagged_count.
    """
    prescanned = get_prescanned()
    zip_map: dict[str, dict] = {}

    for p in prescanned:
        raw_zip = _get_provider_zip(p)
        if not raw_zip or len(raw_zip) < 3:
            continue
        zip3 = raw_zip[:3]
        if zip3 not in zip_map:
            zip_map[zip3] = {
                "zip3": zip3,
                "provider_count": 0,
                "total_paid": 0,
                "flagged_count": 0,
                "risk_scores": [],
            }
        bucket = zip_map[zip3]
        bucket["provider_count"] += 1
        bucket["total_paid"] += p.get("total_paid", 0)
        bucket["risk_scores"].append(p.get("risk_score", 0))
        if _is_flagged(p):
            bucket["flagged_count"] += 1

    results = []
    for bucket in zip_map.values():
        scores = bucket.pop("risk_scores")
        bucket["avg_risk_score"] = round(sum(scores) / len(scores), 1) if scores else 0
        results.append(bucket)

    results.sort(key=lambda x: x["flagged_count"], reverse=True)
    return {"by_zip": results[:50]}


@router.get("/by-city")
async def geography_by_city():
    """
    Aggregate providers by city+state.
    Returns top 100 cities by flagged_count.
    """
    prescanned = get_prescanned()
    city_map: dict[str, dict] = {}

    for p in prescanned:
        state = _get_provider_state(p)
        city = _get_provider_city(p)
        if not city or not state:
            continue
        key = f"{city.upper()}|{state}"
        if key not in city_map:
            city_map[key] = {
                "city": city.upper(),
                "state": state,
                "provider_count": 0,
                "total_paid": 0,
                "flagged_count": 0,
                "risk_scores": [],
                "top_npis": [],
            }
        bucket = city_map[key]
        bucket["provider_count"] += 1
        bucket["total_paid"] += p.get("total_paid", 0)
        bucket["risk_scores"].append(p.get("risk_score", 0))
        if _is_flagged(p):
            bucket["flagged_count"] += 1
            bucket["top_npis"].append(p["npi"])

    results = []
    for bucket in city_map.values():
        scores = bucket.pop("risk_scores")
        bucket["avg_risk_score"] = round(sum(scores) / len(scores), 1) if scores else 0
        bucket["top_npis"] = bucket["top_npis"][:10]  # limit to 10
        results.append(bucket)

    results.sort(key=lambda x: x["flagged_count"], reverse=True)
    return {"by_city": results[:100]}


@router.get("/hotspots")
async def geography_hotspots():
    """
    Find geographic clusters that are fraud hotspots:
    ZIP prefixes with >= 5 flagged providers AND avg risk score > 30.
    """
    prescanned = get_prescanned()
    zip_map: dict[str, dict] = {}

    for p in prescanned:
        raw_zip = _get_provider_zip(p)
        if not raw_zip or len(raw_zip) < 3:
            continue
        zip3 = raw_zip[:3]
        if zip3 not in zip_map:
            zip_map[zip3] = {
                "zip3": zip3,
                "provider_count": 0,
                "total_paid": 0,
                "flagged_count": 0,
                "risk_scores": [],
                "states": set(),
                "cities": set(),
                "flagged_npis": [],
            }
        bucket = zip_map[zip3]
        bucket["provider_count"] += 1
        bucket["total_paid"] += p.get("total_paid", 0)
        bucket["risk_scores"].append(p.get("risk_score", 0))
        state = _get_provider_state(p)
        city = _get_provider_city(p)
        if state:
            bucket["states"].add(state)
        if city:
            bucket["cities"].add(city.upper())
        if _is_flagged(p):
            bucket["flagged_count"] += 1
            bucket["flagged_npis"].append(p["npi"])

    hotspots = []
    for bucket in zip_map.values():
        scores = bucket["risk_scores"]
        avg_risk = sum(scores) / len(scores) if scores else 0
        if bucket["flagged_count"] >= 5 and avg_risk > settings.RISK_THRESHOLD:
            hotspots.append({
                "zip3": bucket["zip3"],
                "provider_count": bucket["provider_count"],
                "total_paid": bucket["total_paid"],
                "flagged_count": bucket["flagged_count"],
                "avg_risk_score": round(avg_risk, 1),
                "states": sorted(bucket["states"]),
                "cities": sorted(bucket["cities"])[:5],
                "flagged_npis": bucket["flagged_npis"][:10],
                "severity": (
                    "CRITICAL" if bucket["flagged_count"] >= 10
                    else "HIGH" if bucket["flagged_count"] >= 5
                    else "WATCH"
                ),
            })

    hotspots.sort(key=lambda x: x["flagged_count"], reverse=True)
    return {"hotspots": hotspots}


@router.get("/state/{state}")
async def geography_state_drilldown(state: str):
    """
    Drill into a state: return city-level breakdown with flagged providers.
    """
    prescanned = get_prescanned()
    state_upper = state.upper()
    city_map: dict[str, dict] = {}

    for p in prescanned:
        p_state = _get_provider_state(p)
        if p_state != state_upper:
            continue
        city = _get_provider_city(p)
        if not city:
            city = "UNKNOWN"
        city_upper = city.upper()
        if city_upper not in city_map:
            city_map[city_upper] = {
                "city": city_upper,
                "state": state_upper,
                "provider_count": 0,
                "total_paid": 0,
                "flagged_count": 0,
                "risk_scores": [],
                "flagged_npis": [],
            }
        bucket = city_map[city_upper]
        bucket["provider_count"] += 1
        bucket["total_paid"] += p.get("total_paid", 0)
        bucket["risk_scores"].append(p.get("risk_score", 0))
        if _is_flagged(p):
            bucket["flagged_count"] += 1
            bucket["flagged_npis"].append({
                "npi": p["npi"],
                "provider_name": p.get("provider_name", ""),
                "risk_score": p.get("risk_score", 0),
                "total_paid": p.get("total_paid", 0),
            })

    results = []
    for bucket in city_map.values():
        scores = bucket.pop("risk_scores")
        bucket["avg_risk_score"] = round(sum(scores) / len(scores), 1) if scores else 0
        bucket["flagged_npis"].sort(key=lambda x: x["risk_score"], reverse=True)
        bucket["flagged_npis"] = bucket["flagged_npis"][:20]
        results.append(bucket)

    results.sort(key=lambda x: x["flagged_count"], reverse=True)

    total_providers = sum(c["provider_count"] for c in results)
    total_flagged = sum(c["flagged_count"] for c in results)
    total_paid = sum(c["total_paid"] for c in results)

    return {
        "state": state_upper,
        "total_providers": total_providers,
        "total_flagged": total_flagged,
        "total_paid": total_paid,
        "cities": results,
    }
