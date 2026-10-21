import asyncio

from fastapi import APIRouter, Depends

from routes.auth import require_user

router = APIRouter(prefix="/api/doj", tags=["doj"], dependencies=[Depends(require_user)])


@router.get("/shortlist")
async def doj_shortlist():
    """Leads ranked for the DOJ Criminal Tip Rewards program, most provable first."""
    from services.doj_shortlist import build_shortlist
    return await asyncio.to_thread(build_shortlist)
