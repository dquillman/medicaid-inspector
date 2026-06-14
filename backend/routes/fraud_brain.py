"""Fraud Brain — cross-source meta-analysis ranking the most probable frauds."""
import asyncio

from fastapi import APIRouter, Depends, Query

from routes.auth import require_user

router = APIRouter(prefix="/api/fraud-brain", tags=["fraud-brain"], dependencies=[Depends(require_user)])


@router.get("/top")
async def top_frauds(limit: int = Query(10, ge=1, le=50), refresh: bool = Query(False)):
    """Top N most probable frauds across every data source, with evidence."""
    from services.fraud_brain import get_top_frauds
    # Scores 106k providers in a worker thread (~1-3s cold, instant cached)
    return await asyncio.to_thread(get_top_frauds, limit, refresh)


@router.get("/membership")
async def fraud_brain_membership(limit: int = Query(100, ge=1, le=500)):
    """{npi: rank} for the Brain's top N — lets every page badge providers that
    are on the Brain list. Served from the same cached compute as /top."""
    from services.fraud_brain import get_top_frauds
    res = await asyncio.to_thread(get_top_frauds, limit, False)
    members = {p["npi"]: i + 1 for i, p in enumerate(res.get("top", []))}
    return {"members": members, "limit": limit}
