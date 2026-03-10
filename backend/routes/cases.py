"""
Case management API routes — enhanced workflow for investigation cases.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.review_store import (
    add_document,
    log_hours,
    set_priority,
    set_due_date,
    get_case_stats,
    get_overdue_cases,
    get_review_item,
    VALID_PRIORITIES,
)
from core.store import get_prescanned

from routes.auth import require_user

router = APIRouter(prefix="/api/cases", tags=["cases"], dependencies=[Depends(require_user)])


def _enrich_item(item: dict) -> dict:
    """Attach provider_name and state from prescan cache."""
    by_npi = {p["npi"]: p for p in get_prescanned()}
    p = by_npi.get(item["npi"], {})
    name = p.get("provider_name") or (p.get("nppes") or {}).get("name") or ""
    state = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state") or ""
    return {**item, "provider_name": name, "state": state}


# ── Document management ──────────────────────────────────────────────────────

class AddDocumentBody(BaseModel):
    filename: str
    description: str = ""
    data_type: str = "other"


@router.post("/{npi}/documents")
async def add_case_document(npi: str, body: AddDocumentBody):
    """Add document metadata to a case."""
    updated = add_document(npi, body.model_dump())
    if updated is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return _enrich_item(updated)


# ── Hours logging ─────────────────────────────────────────────────────────────

class LogHoursBody(BaseModel):
    hours: float
    description: str = ""


@router.post("/{npi}/hours")
async def log_case_hours(npi: str, body: LogHoursBody):
    """Log investigator hours on a case."""
    if body.hours <= 0:
        raise HTTPException(400, "Hours must be positive")
    updated = log_hours(npi, body.hours, body.description)
    if updated is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return _enrich_item(updated)


# ── Priority ──────────────────────────────────────────────────────────────────

class SetPriorityBody(BaseModel):
    priority: str


@router.patch("/{npi}/priority")
async def set_case_priority(npi: str, body: SetPriorityBody):
    """Set case priority (low, medium, high, critical)."""
    try:
        updated = set_priority(npi, body.priority)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return _enrich_item(updated)


# ── Due date ──────────────────────────────────────────────────────────────────

class SetDueDateBody(BaseModel):
    due_date: Optional[str] = None


@router.patch("/{npi}/due-date")
async def set_case_due_date(npi: str, body: SetDueDateBody):
    """Set or clear a case due date (ISO date string, e.g. '2026-04-01')."""
    updated = set_due_date(npi, body.due_date)
    if updated is None:
        raise HTTPException(404, f"Review item not found: {npi}")
    return _enrich_item(updated)


# ── Statistics ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def case_stats():
    """Return aggregate case statistics for the dashboard."""
    return get_case_stats()


@router.get("/overdue")
async def overdue_cases():
    """Return cases past their due date that are still open."""
    items = get_overdue_cases()
    # Enrich each item
    by_npi = {p["npi"]: p for p in get_prescanned()}
    enriched = []
    for item in items:
        p = by_npi.get(item["npi"], {})
        name = p.get("provider_name") or (p.get("nppes") or {}).get("name") or ""
        state = p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state") or ""
        enriched.append({**item, "provider_name": name, "state": state})
    return {"items": enriched, "total": len(enriched)}
