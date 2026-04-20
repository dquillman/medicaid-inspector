"""
Alert rules API routes.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.alert_store import (
    get_rules,
    add_rule,
    update_rule,
    delete_rule,
    evaluate_rules,
    get_last_results,
    VALID_FIELDS,
    VALID_OPERATORS,
)
from core.store import get_prescanned

from routes.auth import require_admin

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(require_admin)])


class ConditionModel(BaseModel):
    field: str
    operator: str
    value: float


class CreateRuleBody(BaseModel):
    name: str
    conditions: list[ConditionModel]
    enabled: bool = True


class UpdateRuleBody(BaseModel):
    name: Optional[str] = None
    conditions: Optional[list[ConditionModel]] = None
    enabled: Optional[bool] = None


@router.get("/rules")
async def list_rules():
    return {"rules": get_rules()}


@router.post("/rules")
async def create_rule(body: CreateRuleBody):
    # Validate conditions
    for cond in body.conditions:
        if cond.field not in VALID_FIELDS:
            raise HTTPException(400, f"Invalid field: {cond.field}. Valid: {sorted(VALID_FIELDS)}")
        if cond.operator not in VALID_OPERATORS:
            raise HTTPException(400, f"Invalid operator: {cond.operator}. Valid: {sorted(VALID_OPERATORS)}")
    rule = add_rule(body.model_dump())
    return rule


@router.patch("/rules/{rule_id}")
async def patch_rule(rule_id: str, body: UpdateRuleBody):
    updates = body.model_dump(exclude_unset=True)
    # Validate conditions if provided
    if "conditions" in updates and updates["conditions"] is not None:
        for cond in updates["conditions"]:
            c = cond if isinstance(cond, dict) else cond.model_dump()
            if c.get("field") not in VALID_FIELDS:
                raise HTTPException(400, f"Invalid field: {c.get('field')}")
            if c.get("operator") not in VALID_OPERATORS:
                raise HTTPException(400, f"Invalid operator: {c.get('operator')}")
    updated = update_rule(rule_id, updates)
    if updated is None:
        raise HTTPException(404, f"Rule not found: {rule_id}")
    return updated


@router.delete("/rules/{rule_id}")
async def remove_rule(rule_id: str):
    if not delete_rule(rule_id):
        raise HTTPException(404, f"Rule not found: {rule_id}")
    return {"deleted": True}


@router.post("/evaluate")
async def evaluate_all_rules():
    """Run all enabled rules against current scanned providers."""
    providers = get_prescanned()
    results = evaluate_rules(providers)
    return {"results": results, "provider_count": len(providers)}


@router.get("/results")
async def latest_results():
    """Return cached results from the last evaluation."""
    return {"results": get_last_results()}
