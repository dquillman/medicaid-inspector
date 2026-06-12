"""
Fraud Brain — cross-source meta-analysis that ranks the most probable frauds.

Fuses every per-provider evidence source the app produces into one composite
0-100 "brain score" with an explainable evidence trail:

  - the 18 rule-based fraud signals (risk_score + flag breadth)
  - Isolation Forest ML anomaly score (persisted ml_scores.json)
  - the precomputed claim-level analyses (unbundling, duplicates, place-of-
    service, modifier abuse, impossible volume)
  - pharmacy / DME high-risk findings
  - doctor-shopping beneficiary findings
  - diagnosis-procedure mismatch flags
  - OIG LEIE exclusion (billing while excluded is the closest thing to a
    smoking gun this data has)
  - dollars at risk (total Medicaid paid, percentile-scaled)

Every input works from the slim cache + persisted/precomputed artifacts, so
the ranking is identical on Cloud Run and the workstation. Results are cached
in memory for CACHE_TTL_SEC and recomputed on demand.
"""
import bisect
import logging
import threading
import time

log = logging.getLogger(__name__)

CACHE_TTL_SEC = 15 * 60

# Component weights — must sum to 1.0 (OIG boost applies on top, capped at 100)
W_RULE_SIGNALS = 0.35   # composite risk_score from the 18 signals
W_ML_ANOMALY   = 0.25   # Isolation Forest score
W_CORROBORATION = 0.20  # independent claim-level analyses that also flagged the NPI
W_DOLLARS      = 0.10   # total_paid percentile
W_FLAG_BREADTH = 0.10   # how many distinct signals fired
# OIG-excluded providers are SKIPPED entirely — they're already barred from
# the program and live on the dedicated Excluded page, so ranking them as
# "probable frauds to investigate" wastes a slot.

_lock = threading.Lock()
_cache: dict = {"result": None, "computed_at": 0.0}

# Precomputed-section name -> (label shown in evidence, points per hit)
_ANALYSIS_SOURCES = {
    "unbundling":  ("Unbundling pattern (claim-level)", 25),
    "duplicates":  ("Duplicate billing pattern (claim-level)", 25),
    "pos":         ("Place-of-service anomaly (claim-level)", 20),
    "modifiers":   ("Modifier abuse pattern (claim-level)", 20),
    "impossible":  ("Impossible daily volume (claim-level)", 30),
    "pharmacy":    ("Pharmacy high-risk profile", 25),
    "dme":         ("DME high-risk profile", 25),
    "doctor_shopping": ("Doctor-shopping beneficiary overlap", 25),
    "diagnosis_flags": ("Diagnosis-procedure mismatch (Medicare proxy)", 20),
}


def _collect_npis(obj) -> set[str]:
    """Pull every 'npi' value out of an arbitrarily-shaped findings payload."""
    npis: set[str] = set()
    if isinstance(obj, dict):
        v = obj.get("npi")
        if isinstance(v, str) and len(v) == 10 and v.isdigit():
            npis.add(v)
        for val in obj.values():
            if isinstance(val, (dict, list)):
                npis.update(_collect_npis(val))
    elif isinstance(obj, list):
        for item in obj:
            npis.update(_collect_npis(item))
    return npis


def _corroboration_index() -> dict[str, list[str]]:
    """Map NPI -> list of analysis-source keys that flagged it.

    Sources come from the precomputed file (present on prod and refreshed by
    the precompute script after every full scan).
    """
    from services.precomputed_store import get_precomputed

    by_npi: dict[str, list[str]] = {}

    claim_patterns = get_precomputed("claim_patterns") or {}
    for section in ("unbundling", "duplicates", "pos", "modifiers", "impossible"):
        for npi in _collect_npis(claim_patterns.get(section) or []):
            by_npi.setdefault(npi, []).append(section)

    for section_key, source_key in (
        ("pharmacy_high_risk", "pharmacy"),
        ("dme_high_risk", "dme"),
        ("doctor_shopping", "doctor_shopping"),
        ("billing_diagnosis_flags", "diagnosis_flags"),
    ):
        for npi in _collect_npis(get_precomputed(section_key) or {}):
            by_npi.setdefault(npi, []).append(source_key)

    return by_npi


def compute_top_frauds(limit: int = 10) -> dict:
    """Score every scanned provider across all sources; return the top N."""
    from core.store import get_prescanned
    from core.oig_store import is_excluded
    from services.ml_scorer import get_ml_score, get_ml_status

    t0 = time.time()
    providers = get_prescanned()
    if not providers:
        return {"top": [], "providers_evaluated": 0,
                "note": "No scanned providers — run a scan first."}

    ml_trained = bool(get_ml_status().get("trained"))
    corroboration = _corroboration_index()

    # total_paid percentile lookup (sorted once, bisect per provider)
    paid_sorted = sorted(float(p.get("total_paid") or 0) for p in providers)
    n_paid = len(paid_sorted)

    scored: list[dict] = []
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue

        # Already barred from the program — belongs on the Excluded page
        if is_excluded(npi)[0]:
            continue

        total_paid = float(p.get("total_paid") or 0)
        risk = float(p.get("risk_score") or 0)

        flag_count = p.get("flag_count")
        if flag_count is None:
            flag_count = len([f for f in (p.get("flags") or []) if f.get("flagged")])
        flag_count = int(flag_count)

        evidence: list[dict] = []
        components: dict[str, float] = {}

        # 1. Rule-based signals
        components["rule_signals"] = risk * W_RULE_SIGNALS
        if risk > 0:
            evidence.append({
                "source": "Rule-based signals",
                "detail": f"Composite risk score {risk:.0f}/100 from {flag_count} fired signal(s)",
                "points": round(components["rule_signals"], 1),
            })

        # 2. ML anomaly
        ml_component = 0.0
        if ml_trained:
            ml = get_ml_score(npi)
            ml_score = ml.get("ml_anomaly_score")
            if ml_score is not None:
                ml_component = float(ml_score) * W_ML_ANOMALY
                if float(ml_score) >= 50:
                    evidence.append({
                        "source": "ML anomaly detection",
                        "detail": f"Isolation Forest score {ml_score:.0f}/100 "
                                  f"({ml.get('ml_percentile', 0):.0f}th percentile)",
                        "points": round(ml_component, 1),
                    })
        components["ml_anomaly"] = ml_component

        # 3. Corroborating claim-level analyses
        corr_sources = corroboration.get(npi, [])
        corr_raw = 0.0
        for s in corr_sources:
            label, pts = _ANALYSIS_SOURCES.get(s, (s, 15))
            corr_raw += pts
            evidence.append({
                "source": "Independent analysis",
                "detail": label,
                "points": round(min(pts, 100) * W_CORROBORATION, 1),
            })
        components["corroboration"] = min(corr_raw, 100) * W_CORROBORATION

        # 4. Dollars at risk
        pct = bisect.bisect_left(paid_sorted, total_paid) / n_paid * 100 if n_paid else 0
        components["dollars"] = pct * W_DOLLARS
        if pct >= 95:
            evidence.append({
                "source": "Financial exposure",
                "detail": f"${total_paid:,.0f} total Medicaid paid "
                          f"(top {100 - pct:.1f}% of all providers)",
                "points": round(components["dollars"], 1),
            })

        # 5. Flag breadth
        components["flag_breadth"] = min(flag_count / 18.0, 1.0) * 100 * W_FLAG_BREADTH

        score = sum(components.values())

        scored.append({
            "npi": npi,
            "provider_name": p.get("provider_name")
                             or (p.get("nppes") or {}).get("name") or "",
            "state": p.get("state")
                     or ((p.get("nppes") or {}).get("address") or {}).get("state", ""),
            "specialty": p.get("specialty")
                         or ((p.get("nppes") or {}).get("taxonomy") or {}).get("description", ""),
            "brain_score": round(min(score, 100.0), 1),
            "total_paid": round(total_paid, 2),
            "risk_score": round(risk, 1),
            "flag_count": flag_count,
            "oig_excluded": False,  # excluded providers are skipped above
            "corroborating_sources": len(corr_sources),
            "components": {k: round(v, 1) for k, v in components.items()},
            "evidence": sorted(evidence, key=lambda e: -e["points"]),
        })

    scored.sort(key=lambda x: (-x["brain_score"], -x["total_paid"]))

    return {
        "top": scored[:limit],
        "providers_evaluated": len(scored),
        "ml_model_used": ml_trained,
        "corroborated_providers": len(corroboration),
        "weights": {
            "rule_signals": W_RULE_SIGNALS, "ml_anomaly": W_ML_ANOMALY,
            "corroboration": W_CORROBORATION, "dollars_at_risk": W_DOLLARS,
            "flag_breadth": W_FLAG_BREADTH,
        },
        "computed_in_ms": int((time.time() - t0) * 1000),
        "computed_at": time.time(),
    }


def get_top_frauds(limit: int = 10, force_refresh: bool = False) -> dict:
    """TTL-cached wrapper around compute_top_frauds."""
    with _lock:
        cached = _cache["result"]
        fresh = (time.time() - _cache["computed_at"]) < CACHE_TTL_SEC
    if cached and fresh and not force_refresh and len(cached.get("top", [])) >= limit:
        return {**cached, "top": cached["top"][:limit], "cached": True}

    result = compute_top_frauds(limit=max(limit, 25))  # compute a few extra for cheap re-serves
    with _lock:
        _cache["result"] = result
        _cache["computed_at"] = time.time()
    return {**result, "top": result["top"][:limit], "cached": False}
