"""
Persistent storage for configurable alert rules.
Disk file: backend/alert_rules.json
"""
import json
import time
import uuid
import operator
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

_RULES_FILE = pathlib.Path(__file__).parent.parent / "alert_rules.json"

# In-memory store: rule_id -> rule dict
_rules: dict[str, dict] = {}

# Cached evaluation results
_last_results: list[dict] = []

VALID_FIELDS = {
    "total_paid", "total_claims", "total_beneficiaries",
    "revenue_per_beneficiary", "claims_per_beneficiary",
    "risk_score", "active_months", "distinct_hcpcs", "flag_count",
}

VALID_OPERATORS = {"gt", "gte", "lt", "lte", "eq"}

_OP_MAP = {
    "gt":  operator.gt,
    "gte": operator.ge,
    "lt":  operator.lt,
    "lte": operator.le,
    "eq":  operator.eq,
}


# ── disk persistence ──────────────────────────────────────────────────────────

def load_rules_from_disk() -> None:
    global _rules
    try:
        if not _RULES_FILE.exists():
            return
        raw = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
        _rules = {r["id"]: r for r in raw.get("rules", [])}
        print(f"[alert_store] Loaded {len(_rules)} alert rules from disk")
    except Exception as e:
        print(f"[alert_store] Could not load alert rules: {e}")


def save_rules_to_disk() -> None:
    try:
        atomic_write_json(_RULES_FILE, {"rules": list(_rules.values())})
    except Exception as e:
        print(f"[alert_store] Could not save alert rules: {e}")


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_rules() -> list[dict]:
    """Return all rules sorted by created_at DESC."""
    rules = list(_rules.values())
    rules.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return rules


def add_rule(rule: dict) -> dict:
    """Create a new rule. Returns the saved rule dict."""
    rule_id = str(uuid.uuid4())
    now = time.time()
    new_rule = {
        "id": rule_id,
        "name": rule.get("name", "Untitled Rule"),
        "conditions": rule.get("conditions", []),
        "enabled": rule.get("enabled", True),
        "created_at": now,
    }
    _rules[rule_id] = new_rule
    save_rules_to_disk()
    return new_rule


def update_rule(rule_id: str, updates: dict) -> Optional[dict]:
    """Update an existing rule. Returns updated rule or None if not found."""
    rule = _rules.get(rule_id)
    if rule is None:
        return None
    for key in ("name", "conditions", "enabled"):
        if key in updates:
            rule[key] = updates[key]
    save_rules_to_disk()
    return rule


def delete_rule(rule_id: str) -> bool:
    """Delete a rule. Returns True if found and deleted."""
    if rule_id not in _rules:
        return False
    del _rules[rule_id]
    save_rules_to_disk()
    return True


# ── evaluation ────────────────────────────────────────────────────────────────

def _get_field_value(provider: dict, field: str) -> float:
    """Extract a numeric field value from a provider dict."""
    if field == "flag_count":
        return len(provider.get("flags", []))
    return float(provider.get(field, 0) or 0)


def _matches_rule(provider: dict, rule: dict) -> bool:
    """Check if a provider matches ALL conditions of a rule."""
    for cond in rule.get("conditions", []):
        field = cond.get("field", "")
        op_name = cond.get("operator", "")
        value = float(cond.get("value", 0))
        if field not in VALID_FIELDS or op_name not in VALID_OPERATORS:
            continue
        actual = _get_field_value(provider, field)
        op_fn = _OP_MAP[op_name]
        if not op_fn(actual, value):
            return False
    return True


def evaluate_rules(providers: list[dict]) -> list[dict]:
    """
    Run all enabled rules against the provider list.
    Returns list of {rule, matching_providers} for rules with matches.
    Caches results for GET /api/alerts/results.
    """
    global _last_results
    results = []
    for rule in _rules.values():
        if not rule.get("enabled", True):
            continue
        if not rule.get("conditions"):
            continue
        matches = []
        for p in providers:
            if _matches_rule(p, rule):
                matches.append({
                    "npi": p.get("npi", ""),
                    "provider_name": p.get("provider_name") or (p.get("nppes") or {}).get("name") or "",
                    "state": p.get("state") or (p.get("nppes") or {}).get("address", {}).get("state") or "",
                    "risk_score": p.get("risk_score", 0),
                    "total_paid": p.get("total_paid", 0),
                    "flag_count": len(p.get("flags", [])),
                })
        results.append({
            "rule": rule,
            "matching_providers": matches,
            "match_count": len(matches),
        })
    _last_results = results
    return results


def get_last_results() -> list[dict]:
    """Return the cached results from the last evaluation."""
    return _last_results
