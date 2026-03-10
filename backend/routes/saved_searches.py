"""
Saved search endpoints — save/load filter configurations.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from routes.auth import require_user
from core.saved_search_store import (
    list_saved_searches,
    create_saved_search,
    delete_saved_search,
)

router = APIRouter(prefix="/api/saved-searches", tags=["saved-searches"], dependencies=[Depends(require_user)])


class CreateSearchRequest(BaseModel):
    name: str
    filters: dict


@router.get("")
async def get_saved_searches():
    return {"searches": list_saved_searches()}


@router.post("")
async def save_search(req: CreateSearchRequest):
    if not req.name.strip():
        raise HTTPException(400, "Name is required")
    search = create_saved_search(req.name.strip(), req.filters)
    return {"search": search}


@router.delete("/{search_id}")
async def remove_saved_search(search_id: str):
    if not delete_saved_search(search_id):
        raise HTTPException(404, "Saved search not found")
    return {"ok": True, "deleted": search_id}
