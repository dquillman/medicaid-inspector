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

# Component weights — must sum to 1.0 (boosts apply on top, capped at 100)
W_RULE_SIGNALS = 0.35   # composite risk_score from the 18 signals
W_ML_ANOMALY   = 0.25   # Isolation Forest score
W_CORROBORATION = 0.20  # independent claim-level analyses that also flagged the NPI
W_DOLLARS      = 0.10   # total_paid percentile
W_FLAG_BREADTH = 0.10   # how many distinct signals fired

# When the SUPERVISED model is trained (learned from the user's own
# confirmed-fraud/dismissed labels in the Review Queue), its fraud
# probability joins the blend at this weight and the base components are
# scaled by (1 - W_SUPERVISED) so the total still sums to 1.0.
W_SUPERVISED = 0.25
# Review-queue confirmed frauds always get a flat boost so they surface on
# the board regardless of dollar size. OIG-excluded providers are SKIPPED —
# they're already barred and live on the dedicated Excluded page — UNLESS
# they're confirmed_fraud, in which case the exclusion stacks as additional
# evidence. Total score stays capped at 100.
CONFIRMED_FRAUD_BOOST = 25.0
OIG_BOOST = 25.0
DEACTIVATED_NPI_BOOST = 20.0  # billing Medicaid under a CMS-deactivated NPI

# Size-bias correction. The single biggest ranking flaw was giant institutions
# (hospital systems) topping the board purely on scale. Two fixes:
#  (a) "dollars at risk" is a WITHIN-COHORT percentile (cohort = taxonomy /
#      specialty), so a hospital's spend is judged against other hospitals, not
#      against strip-mall PCA mills.
#  (b) providers that look institutional (hospital-ish taxonomy, or a very broad
#      code mix across a very large beneficiary panel) get their score dampened
#      UNLESS a provider-specific (non-size) signal fires — confirmed fraud, OIG
#      exclusion, any claim-level corroboration, or a strong ML anomaly.
# Strict large-institution terms only. NOT "clinic"/"center" — a fraud PCA mill
# is often a "Clinic/Center", and those must NOT be dampened.
INSTITUTIONAL_KEYWORDS = (
    "hospital", "health system", "medical center", "health network",
    "healthcare system", "health care system", "regional medical",
)
# A genuine institution bills a BROAD code mix to a LARGE panel. A fraud mill
# bills a NARROW mix (high concentration) — so this size+breadth test cleanly
# separates "real hospital/FQHC" from "PCA/NEMT mill" and only dampens the
# former. ML anomaly and claim-level corroboration are EXCLUDED from the
# exemption below because, for huge institutions, those fire as a function of
# size — only confirmed-fraud and OIG exclusion are truly size-independent.
INSTITUTIONAL_DISTINCT_HCPCS = 80   # broad code mix
INSTITUTIONAL_BENES = 5000          # large panel
INSTITUTIONAL_DAMPEN = 0.45         # multiplier applied to a size-only giant

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
    from core.deactivation_store import get_deactivation
    from services.ml_scorer import get_ml_score, get_ml_status

    t0 = time.time()
    providers = get_prescanned()
    if not providers:
        return {"top": [], "providers_evaluated": 0,
                "note": "No scanned providers — run a scan first."}

    ml_trained = bool(get_ml_status().get("trained"))
    corroboration = _corroboration_index()

    # Excluded providers re-enter the ranking only when confirmed fraud
    from core.review_store import get_review_queue
    confirmed_fraud_npis = {
        i.get("npi") for i in get_review_queue() if i.get("status") == "confirmed_fraud"
    }

    # Label-trained supervised model — empty dict until the user has labeled
    # >=10 providers and trained it (ML Model page)
    from services.supervised_scorer import get_predictions_snapshot
    supervised = get_predictions_snapshot()
    sup_active = bool(supervised)
    base_scale = (1.0 - W_SUPERVISED) if sup_active else 1.0

    # total_paid percentile lookup (sorted once, bisect per provider)
    paid_sorted = sorted(float(p.get("total_paid") or 0) for p in providers)
    n_paid = len(paid_sorted)

    # within-cohort dollar percentile — cohort = taxonomy/specialty bucket
    from collections import defaultdict
    def _cohort_key(prov: dict) -> str:
        return (prov.get("specialty") or "").strip().lower() or "unknown"
    cohort_paid: dict[str, list[float]] = defaultdict(list)
    for p in providers:
        cohort_paid[_cohort_key(p)].append(float(p.get("total_paid") or 0))
    for arr in cohort_paid.values():
        arr.sort()

    scored: list[dict] = []
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue

        # Already barred from the program — belongs on the Excluded page,
        # unless the review queue confirmed the fraud
        oig = is_excluded(npi)[0]
        if oig and npi not in confirmed_fraud_npis:
            continue
        deact_date = get_deactivation(npi)

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
        ml_raw = 0.0
        if ml_trained:
            ml = get_ml_score(npi)
            ml_score = ml.get("ml_anomaly_score")
            if ml_score is not None:
                ml_raw = float(ml_score)
                ml_component = ml_raw * W_ML_ANOMALY
                if ml_raw >= 50:
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

        # 4. Dollars at risk — WITHIN-COHORT percentile (not global), so scale
        #    is judged against same-specialty peers.
        ck = _cohort_key(p)
        cohort_arr = cohort_paid.get(ck) or paid_sorted
        n_cohort = len(cohort_arr)
        pct = bisect.bisect_left(cohort_arr, total_paid) / n_cohort * 100 if n_cohort else 0
        components["dollars"] = pct * W_DOLLARS
        if pct >= 95:
            evidence.append({
                "source": "Financial exposure",
                "detail": f"${total_paid:,.0f} Medicaid paid — top {100 - pct:.1f}% "
                          f"among {ck} peers (n={n_cohort:,})",
                "points": round(components["dollars"], 1),
            })

        # 5. Flag breadth
        components["flag_breadth"] = min(flag_count / 18.0, 1.0) * 100 * W_FLAG_BREADTH

        # Supervised model trained on the user's review labels
        if sup_active:
            for k in components:
                components[k] *= base_scale
            prob = float((supervised.get(npi) or {}).get("fraud_probability") or 0.0)
            components["supervised_ml"] = prob * 100 * W_SUPERVISED
            if prob >= 0.5:
                evidence.append({
                    "source": "Supervised ML (trained on your labels)",
                    "detail": f"{prob:.0%} fraud probability from the review-queue-trained model",
                    "points": round(components["supervised_ml"], 1),
                })

        score = sum(components.values())

        confirmed = npi in confirmed_fraud_npis

        # Institutional-giant suppression: a large institution with NO
        # provider-specific signal beyond raw scale gets dampened so it stops
        # crowding out small, genuinely anomalous billers.
        specialty_l = (p.get("specialty") or "").lower()
        distinct_hcpcs = float(p.get("distinct_hcpcs") or 0)
        benes = float(p.get("total_beneficiaries") or 0)
        is_institutional = (
            any(kw in specialty_l for kw in INSTITUTIONAL_KEYWORDS)
            or (distinct_hcpcs >= INSTITUTIONAL_DISTINCT_HCPCS and benes >= INSTITUTIONAL_BENES)
        )
        # Only confirmed-fraud / OIG exclusion are size-independent PROVABLE
        # signals. Deactivated-NPI is NOT — NPPES deactivation is unreliable
        # (reactivated/replaced NPIs, billing that predates deactivation), so it
        # must NOT rescue a giant institution from dampening (that's how Easter
        # Seals / NYC Health+Hospitals were topping the Brain).
        strong_specific = confirmed or oig
        dampened = is_institutional and not strong_specific
        if dampened:
            score *= INSTITUTIONAL_DAMPEN
            evidence.append({
                "source": "Size adjustment",
                "detail": "Large institutional provider with no provider-specific "
                          "fraud signal beyond scale — score dampened to avoid "
                          "crowding out smaller anomalies",
                "points": 0,
            })

        if confirmed:
            score += CONFIRMED_FRAUD_BOOST
            evidence.append({
                "source": "Confirmed fraud",
                "detail": "Marked confirmed_fraud in the Review Queue",
                "points": CONFIRMED_FRAUD_BOOST,
            })
        if oig:  # only reachable when confirmed_fraud
            score += OIG_BOOST
            evidence.append({
                "source": "OIG LEIE exclusion",
                "detail": "On the federal exclusion list while present in "
                          "Medicaid billing data",
                "points": OIG_BOOST,
            })
        if deact_date:
            # NO score boost. NPPES "deactivation" is NOT provable fraud: NPIs get
            # reactivated/replaced without the file tracking it, and ~70% of
            # matches billed only BEFORE deactivation (legitimate prior activity).
            # It is a LEAD TO VERIFY, never proof — so it informs the flag with an
            # honest caveat but does not drive the ranking.
            evidence.append({
                "source": "Deactivated-NPI lead (UNVERIFIED)",
                "detail": f"NPPES shows this NPI deactivated {deact_date} — verify against "
                          "current NPPES before relying on it; NPPES deactivation is "
                          "unreliable here and is NOT proof of fraud",
                "points": 0,
            })

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
            "oig_excluded": oig,
            "confirmed_fraud": confirmed,
            "deactivated_npi": bool(deact_date),
            "size_dampened": dampened,
            "corroborating_sources": len(corr_sources),
            "components": {k: round(v, 1) for k, v in components.items()},
            "evidence": sorted(evidence, key=lambda e: -e["points"]),
        })

    scored.sort(key=lambda x: (-x["brain_score"], -x["total_paid"]))

    return {
        "top": scored[:limit],
        "providers_evaluated": len(scored),
        "ml_model_used": ml_trained,
        "supervised_model_used": sup_active,
        "corroborated_providers": len(corroboration),
        "weights": {
            "rule_signals": W_RULE_SIGNALS, "ml_anomaly": W_ML_ANOMALY,
            "corroboration": W_CORROBORATION, "dollars_at_risk": W_DOLLARS,
            "flag_breadth": W_FLAG_BREADTH,
            "confirmed_fraud_boost": CONFIRMED_FRAUD_BOOST, "oig_boost": OIG_BOOST,
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
