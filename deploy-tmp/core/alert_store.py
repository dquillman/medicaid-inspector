"""
Persistent storage for configurable alert rules.
Disk file: backend/alert_rules.json
"""
import json
import logging
import time
import uuid
import operator
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

log = logging.getLogger(__name__)

_RULES_FILE = pathlib.Path(__file__).parent.parent / "alert_rules.json"

# In-memory store: rule_id -> rule dict
_rules: dict[str, dict] = {}

# Cached evaluation results
_last_results: list[dict] = []

# ── Signal-level fields ──────────────────────────────────────────────────────
# All 17 built-in fraud signals whose scores can be queried in custom rules.
SIGNAL_IDS = [
    "billing_concentration", "revenue_per_bene_outlier", "claims_per_bene_anomaly",
    "billing_ramp_rate", "bust_out_pattern", "ghost_billing", "total_spend_outlier",
    "billing_consistency", "bene_concentration", "upcoding_pattern",
    "address_cluster_risk", "oig_excluded", "specialty_mismatch",
    "corporate_shell_risk", "geographic_impossibility", "dead_npi_billing",
    "new_provider_explosion", "ghost_employee_billing", "servicing_npi_concentration",
    "beneficiary_sharing_anomaly", "pecos_enrollment_gap", "reassignment_chain_depth",
]

SIGNAL_SCORE_FIELDS = {f"{sid}_score" for sid in SIGNAL_IDS}

VALID_FIELDS = {
    # Aggregate metrics (original)
    "total_paid", "total_claims", "total_beneficiaries",
    "revenue_per_beneficiary", "claims_per_beneficiary",
    "risk_score", "active_months", "distinct_hcpcs", "flag_count",
    # Signal-level scores (new)
    *SIGNAL_SCORE_FIELDS,
}

VALID_OPERATORS = {"gt", "gte", "lt", "lte", "eq"}

_OP_MAP = {
    "gt":  operator.gt,
    "gte": operator.ge,
    "lt":  operator.lt,
    "lte": operator.le,
    "eq":  operator.eq,
}


# ── validation ───────────────────────────────────────────────────────────────

def validate_conditions(conditions: list[dict]) -> list[str]:
    """
    Validate a list of condition dicts.
    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    if not conditions:
        errors.append("At least one condition is required.")
        return errors

    seen: set[tuple] = set()
    for i, cond in enumerate(conditions):
        field = cond.get("field", "")
        op_name = cond.get("operator", "")
        value = cond.get("value")

        if not field or field not in VALID_FIELDS:
            errors.append(f"Condition {i+1}: invalid field '{field}'. Valid fields: {sorted(VALID_FIELDS)}")
        if not op_name or op_name not in VALID_OPERATORS:
            errors.append(f"Condition {i+1}: invalid operator '{op_name}'. Valid: {sorted(VALID_OPERATORS)}")

        # Value must be numeric
        if value is None:
            errors.append(f"Condition {i+1}: value is required.")
        else:
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"Condition {i+1}: value must be numeric, got '{value}'.")

        # Duplicate detection
        key = (field, op_name, value)
        if key in seen:
            errors.append(f"Condition {i+1}: duplicate of an earlier condition ({field} {op_name} {value}).")
        seen.add(key)

    return errors


def validate_rule_name(name: str) -> list[str]:
    """Validate rule name. Returns list of error strings."""
    errors: list[str] = []
    if not name or not name.strip():
        errors.append("Rule name is required.")
    elif len(name.strip()) > 200:
        errors.append("Rule name must be 200 characters or fewer.")
    return errors


# ── disk persistence ──────────────────────────────────────────────────────────

def load_rules_from_disk() -> None:
    global _rules
    try:
        if not _RULES_FILE.exists():
            return
        raw = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
        _rules = {r["id"]: r for r in raw.get("rules", [])}
        log.info("[alert_store] Loaded %d alert rules from disk", len(_rules))
    except Exception as e:
        log.warning("[alert_store] Could not load alert rules: %s", e)


def save_rules_to_disk() -> None:
    try:
        atomic_write_json(_RULES_FILE, {"rules": list(_rules.values())})
    except Exception as e:
        log.warning("[alert_store] Could not save alert rules: %s", e)


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
        return float(len(provider.get("flags", [])))

    # Signal-level score fields: e.g. "billing_concentration_score"
    if field.endswith("_score") and field in SIGNAL_SCORE_FIELDS:
        signal_id = field[: -len("_score")]  # strip trailing "_score"
        for sig in provider.get("signal_results", []):
            if sig.get("signal") == signal_id:
                return float(sig.get("score", 0))
        return 0.0

    return float(provider.get(field, 0) or 0)


def _matches_rule(provider: dict, rule: dict) -> bool:
    """
    Check if a provider matches ALL conditions of a rule.
    A rule with any invalid condition does NOT match (fail-closed).
    """
    conditions = rule.get("conditions", [])
    if not conditions:
        return False

    for cond in conditions:
        field = cond.get("field", "")
        op_name = cond.get("operator", "")
        value = cond.get("value")

        # Invalid condition → fail-closed (no match)
        if field not in VALID_FIELDS or op_name not in VALID_OPERATORS:
            log.warning(
                "Rule '%s' has invalid condition (field=%r, op=%r) — skipping rule entirely",
                rule.get("name", rule.get("id")), field, op_name,
            )
            return False

        try:
            threshold = float(value)
        except (TypeError, ValueError):
            log.warning(
                "Rule '%s' has non-numeric value %r for field %r — skipping rule entirely",
                rule.get("name", rule.get("id")), value, field,
            )
            return False

        actual = _get_field_value(provider, field)
        op_fn = _OP_MAP[op_name]
        if not op_fn(actual, threshold):
            return False

    return True


def evaluate_rules(providers: list[dict]) -> list[dict]:
    """
    Run all enabled rules against the provider list.
    Returns list of {rule, matching_providers, match_count} for each enabled rule.
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
