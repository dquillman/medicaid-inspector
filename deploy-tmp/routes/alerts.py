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
    validate_conditions,
    validate_rule_name,
    VALID_FIELDS,
    VALID_OPERATORS,
)
from core.store import get_prescanned
from core.audit_log import log_action

from routes.auth import require_admin

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


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
async def list_rules(_user: dict = Depends(require_admin)):
    return {"rules": get_rules()}


@router.get("/fields")
async def list_fields(_user: dict = Depends(require_admin)):
    """Return available fields and operators for building rule conditions."""
    return {
        "fields": sorted(VALID_FIELDS),
        "operators": sorted(VALID_OPERATORS),
    }


@router.post("/rules")
async def create_rule(body: CreateRuleBody, user: dict = Depends(require_admin)):
    # Validate name
    name_errors = validate_rule_name(body.name)
    if name_errors:
        raise HTTPException(400, detail={"errors": name_errors})

    # Validate conditions
    cond_dicts = [c.model_dump() for c in body.conditions]
    cond_errors = validate_conditions(cond_dicts)
    if cond_errors:
        raise HTTPException(400, detail={"errors": cond_errors})

    rule = add_rule(body.model_dump())

    log_action(
        "alert_rule_created", "alert_rule", rule["id"],
        details={"name": rule["name"], "conditions": rule["conditions"]},
        user=user.get("username", "admin"),
    )
    return rule


@router.patch("/rules/{rule_id}")
async def patch_rule(rule_id: str, body: UpdateRuleBody, user: dict = Depends(require_admin)):
    updates = body.model_dump(exclude_unset=True)

    # Validate name if provided
    if "name" in updates and updates["name"] is not None:
        name_errors = validate_rule_name(updates["name"])
        if name_errors:
            raise HTTPException(400, detail={"errors": name_errors})

    # Validate conditions if provided
    if "conditions" in updates and updates["conditions"] is not None:
        cond_dicts = [
            c if isinstance(c, dict) else c.model_dump()
            for c in updates["conditions"]
        ]
        cond_errors = validate_conditions(cond_dicts)
        if cond_errors:
            raise HTTPException(400, detail={"errors": cond_errors})

    updated = update_rule(rule_id, updates)
    if updated is None:
        raise HTTPException(404, f"Rule not found: {rule_id}")

    log_action(
        "alert_rule_updated", "alert_rule", rule_id,
        details={"updates": {k: v for k, v in updates.items() if v is not None}},
        user=user.get("username", "admin"),
    )
    return updated


@router.delete("/rules/{rule_id}")
async def remove_rule(rule_id: str, user: dict = Depends(require_admin)):
    # Capture rule name before deletion for audit
    existing = next((r for r in get_rules() if r["id"] == rule_id), None)
    if not delete_rule(rule_id):
        raise HTTPException(404, f"Rule not found: {rule_id}")

    log_action(
        "alert_rule_deleted", "alert_rule", rule_id,
        details={"name": existing["name"] if existing else "unknown"},
        user=user.get("username", "admin"),
    )
    return {"deleted": True}


@router.post("/evaluate")
async def evaluate_all_rules(user: dict = Depends(require_admin)):
    """Run all enabled rules against current scanned providers."""
    providers = get_prescanned()
    results = evaluate_rules(providers)
    total_matches = sum(r["match_count"] for r in results)

    log_action(
        "alert_evaluated", "system", "manual",
        details={"rules_evaluated": len(results), "total_matches": total_matches,
                 "provider_count": len(providers), "trigger": "manual"},
        user=user.get("username", "admin"),
    )
    return {"results": results, "provider_count": len(providers)}


@router.get("/results")
async def latest_results(_user: dict = Depends(require_admin)):
    """Return cached results from the last evaluation."""
    return {"results": get_last_results()}
