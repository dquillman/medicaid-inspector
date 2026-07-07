"""
Ownership chain tracing API routes.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_user
from services.ownership_tracer import trace_ownership_network_async, find_ownership_clusters

router = APIRouter(prefix="/api/ownership-trace", tags=["ownership"], dependencies=[Depends(require_user)])
log = logging.getLogger(__name__)


@router.get("/provider/{npi}")
async def trace_provider_ownership(npi: str):
    """
    Trace the ownership network for a provider — find all entities connected
    via shared authorized official, address, or phone/fax.
    """
    try:
        result = await trace_ownership_network_async(npi)
        if not result.get("found"):
            raise HTTPException(404, result.get("error", "Provider not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("Ownership trace failed for %s: %s", npi, e)
        raise HTTPException(500, str(e))


@router.get("/clusters")
async def ownership_clusters(min_size: int = 2, limit: int = 50):
    """
    Find all ownership clusters — groups of providers sharing the same
    authorized official. Helps identify hidden ownership networks.
    """
    try:
        return find_ownership_clusters(min_size=min_size, limit=limit)
    except Exception as e:
        log.error("Ownership clusters failed: %s", e)
        raise HTTPException(500, str(e))
