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

# ── Data-recency awareness ────────────────────────────────────────────────────
# Recency is the fastest proxy for "is this outlier still happening" — a
# provider whose last claim was years ago is a recovery lead, not an active
# scheme. It is surfaced as SEPARATE, transparent fields (last_active_month /
# data_age_months / recency badge) and NEVER folded into brain_score: the
# fraud-signal score stays auditable and unchanged.
#
# The fresh/aging/stale badge is relative to the NEWEST claim month on the
# board (dataset max), not the wall clock — a T-MSIS extract always trails
# today by months, and calendar-relative thresholds would mark the entire
# dataset stale. data_age_months IS calendar-relative (months since today) so
# callers still get the absolute number.
RECENCY_FRESH_MONTHS = 6    # within 6 months of the dataset's newest claim
RECENCY_AGING_MONTHS = 24   # within 24 months; older than that = stale

# Beyond this CALENDAR age, a stale case is likely past the recovery window too:
# the False Claims Act statute of limitations is 6 years from the violation
# (stretchable to a 10-year hard cap only under the govt-didn't-know tolling
# exception, which needs a specific legal determination — not a default). So a
# provider whose last claim is >6 years old is neither an active scheme nor a
# clean recovery: it gets its own "expired" tier so it visually separates from
# the recoverable stale cases instead of crowding them under one badge. This is
# CALENDAR-based (real statute clock), unlike the dataset-relative tiers above;
# it always implies stale, so it slots in as the deepest tier.
FCA_RECOVERY_WINDOW_MONTHS = 72  # 6 years


def _ym_index(ym: str | None) -> int | None:
    """'YYYY-MM' -> absolute month index (year*12+month), else None."""
    s = str(ym or "").strip()
    if len(s) < 7 or not (s[:4].isdigit() and s[5:7].isdigit()):
        return None
    return int(s[:4]) * 12 + int(s[5:7])


def months_since(ym: str | None, now: float | None = None) -> int | None:
    """Whole months between 'YYYY-MM' and today (calendar). None if unparseable."""
    idx = _ym_index(ym)
    if idx is None:
        return None
    t = time.localtime(now if now is not None else time.time())
    return max(0, (t.tm_year * 12 + t.tm_mon) - idx)


_newest_month_cache: dict = {"idx": None, "at": 0.0}


def dataset_newest_month_index() -> int | None:
    """Max claim-month index across the prescan cache — the 'now' the recency
    badge is measured against (see the module note: dataset-relative, not wall
    clock). Cached for CACHE_TTL_SEC; only changes on a rescan. So the badge
    means the same thing on the Fraud Brain board, the Review Queue, and the
    provider detail page."""
    now = time.time()
    if _newest_month_cache["idx"] is not None and (now - _newest_month_cache["at"]) < CACHE_TTL_SEC:
        return _newest_month_cache["idx"]
    from core.store import get_prescanned
    newest = max(
        (i for i in (_ym_index(p.get("last_month")) for p in get_prescanned()) if i is not None),
        default=None,
    )
    _newest_month_cache["idx"] = newest
    _newest_month_cache["at"] = now
    return newest


def recency_badge(last_month: str | None, newest_idx: int | None = None) -> str | None:
    """'fresh' / 'aging' / 'stale' / 'expired' for a last-claim month. None if
    unknown. 'expired' is CALENDAR-based (last claim > the FCA recovery window,
    ~6 years) and takes precedence — it's the deepest tier, separating likely-
    unrecoverable providers from recoverable 'stale' ones. The other three are
    dataset-relative (vs the newest claim month); pass newest_idx to avoid
    recomputing it per-row in a batch."""
    idx = _ym_index(last_month)
    if idx is None:
        return None
    # Past the recovery window entirely? (calendar age, real statute clock)
    age = months_since(last_month)
    if age is not None and age > FCA_RECOVERY_WINDOW_MONTHS:
        return "expired"
    if newest_idx is None:
        newest_idx = dataset_newest_month_index()
    if newest_idx is None:
        return None
    behind = newest_idx - idx
    return ("fresh" if behind <= RECENCY_FRESH_MONTHS
            else "aging" if behind <= RECENCY_AGING_MONTHS
            else "stale")

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
# DEPRECATED / UNUSED as of the candidate-engine / case-ledger separation:
# review-queue disposition (confirmed_fraud) no longer boosts the Brain score —
# case decisions must not steer the ranking they were made from. OIG-excluded
# providers are filtered from the candidate ranking by federal-LEIE *data*
# (they live on the Excluded page), independent of any case decision. These
# constants are retained only to avoid breaking any external reference; they are
# not applied to the score.
CONFIRMED_FRAUD_BOOST = 25.0  # no longer applied
OIG_BOOST = 25.0  # no longer applied
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
    "impossible":  ("Extreme daily volume — verify vs group/facility billing (claim-level)", 15),
    "pharmacy":    ("Pharmacy high-risk profile", 25),
    "dme":         ("DME high-risk profile", 25),
    "doctor_shopping": ("Doctor-shopping beneficiary overlap", 25),
    "diagnosis_flags": ("Diagnosis-procedure mismatch (Medicare proxy)", 20),
}

# Human labels for the ML feature columns, so the anomaly evidence can name
# WHICH features made a provider an outlier instead of emitting a black-box
# percentile. Keys must match services.ml_scorer.FEATURE_COLS (extra labels are
# harmless — only keys present in a provider's importances are ever shown).
_FEATURE_LABELS = {
    "total_paid": "total paid",
    "total_claims": "total claims",
    "total_beneficiaries": "beneficiary count",
    "revenue_per_beneficiary": "revenue per beneficiary",
    "claims_per_beneficiary": "claims per beneficiary",
    "active_months": "active months",
    "distinct_hcpcs": "distinct procedure codes",
    "flag_count": "fired rule signals",
}


# Taxonomy/specialty substrings that mark an ORGANIZATIONAL provider (a facility
# billing under one NPI), for which "physically impossible daily volume" is
# meaningless — a hospital, lab, FQHC, agency or DME supplier legitimately serves
# far more than one clinician's worth of patients per day. Matched against the
# provider's specialty (taxonomy description), which is present in the cache;
# NPPES entity_type (the authoritative individual/org flag) is NOT persisted in
# the scan cache, so taxonomy is the available proxy at ranking time.
_ORG_SPECIALTY_MARKERS = (
    "agency", "center", "hospital", "laborator", "clinic", "pharmac", "supplier",
    "supplies", "equipment", "facility", "education", "home health", "ambulance",
    "nursing", "dialysis", "esrd", "fqhc", "transport", "residential", "school",
    "treatment", "program", "institution", "assisted living", "rehabilitation",
    "skilled nursing", "health system", "hospice",
)


def _is_org_specialty(specialty: str | None) -> bool:
    s = (specialty or "").lower()
    return any(m in s for m in _ORG_SPECIALTY_MARKERS)


# Corroboration sources that are meaningless for an organizational NPI (a
# facility/agency billing under one number) and over-fire on them. Verified
# against the precomputed lists:
#   - "impossible": 43% of all providers, dominated by hospitals/FQHCs/labs.
#   - "modifiers":  306/500 are General Acute Care Hospitals (a hospital billing
#     procedures alongside E&M is normal, not modifier-25 abuse).
#   - "pos" (surgical-in-office): dominated by legit proceduralist orgs
#     (ambulatory surgical centers, critical access hospitals).
#   - "doctor_shopping": dominated by home-health/personal-care AGENCIES whose
#     patients legitimately see many providers (care coordination) — patient
#     overlap is normal for an agency, not evidence the agency is shopping.
# Unbundling is intentionally EXCLUDED — a lab billing component codes instead of
# the panel is the canonical unbundling case, so org-suppressing it would drop
# real signal.
_INDIVIDUAL_ONLY_SOURCES = {"impossible", "modifiers", "pos", "doctor_shopping"}


def _ml_driver_text(prov: dict, importances: dict | None, feat_means: dict) -> str:
    """Name the top features that made this provider an ML outlier, each with
    its magnitude (|z|) and direction vs the peer mean.

    Turns "Isolation Forest 99th percentile" (a black box an investigator can't
    defend) into "most unusual on total claims (25.3σ above peer mean), ..." so a
    reviewer can immediately judge whether the anomaly is fraud-relevant or just
    a large-provider artifact. Direction is derived at request time by comparing
    the provider's raw value to the population mean (monotonic — correct even for
    transformed features)."""
    if not importances:
        return ""
    ranked = sorted(importances.items(), key=lambda kv: abs(kv[1]), reverse=True)
    parts: list[str] = []
    for col, z in ranked:
        if abs(z) < 0.75:        # within ~0.75σ of the mean — not a real driver
            continue
        label = _FEATURE_LABELS.get(col, col.replace("_", " "))
        raw = float(prov.get(col) or 0)
        direction = "above" if raw >= feat_means.get(col, 0.0) else "below"
        parts.append(f"{label} ({abs(z):.1f}σ {direction} peer mean)")
        if len(parts) >= 3:
            break
    return ", ".join(parts)


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

    # Pharmacy: high-COST drug concentration alone is standard of care for many
    # specialties (retina/ophthalmology anti-VEGF, oncology, rheumatology and
    # neurology infusions) — NOT fraud. The pharmacy_high_risk list also pads with
    # zero-flag drug billers. Only controlled-substance or unclassified-code
    # concentration is a genuine diversion signal. Measured on the precomputed
    # list: of 500, only 122 (24%) carry a real signal; 243 are high-cost-only
    # (100 Ophthalmology + 48 Retina) and 135 have no signal at all. Corroborate
    # only the real-signal subset.
    pharm = get_precomputed("pharmacy_high_risk") or {}
    for r in (pharm.get("providers") or []):
        if not isinstance(r, dict):
            continue
        npi = r.get("npi")
        if npi and ((r.get("controlled_pct") or 0) > 15 or (r.get("unclassified_pct") or 0) > 10):
            by_npi.setdefault(npi, []).append("pharmacy")

    # billing_diagnosis_flags is intentionally NOT a corroboration source: its
    # detector (routes/billing_codes._build_diag_flag_for_provider) compares two
    # STATIC reference tables (HCPCS_TO_ICD10 vs the rule's valid_icd_prefixes)
    # for the codes a provider bills — it never looks at the provider's actual
    # diagnoses, so it can only fire on a reference-table inconsistency and flags
    # 0/106k. The real diagnosis-mismatch signal (diagnosis_procedure_mismatch,
    # MUP-based) is already counted in the rule-signals component — adding this
    # back would be a broken, double-counting wire.
    for section_key, source_key in (
        ("dme_high_risk", "dme"),
        ("doctor_shopping", "doctor_shopping"),
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

    # Per-feature population means — one pass over all providers — so the ML
    # evidence can state direction ("X σ ABOVE/BELOW the peer mean") instead of
    # an unexplained percentile. Cheap and request-time; no retrain needed.
    feat_means: dict[str, float] = {}
    if ml_trained:
        from services.ml_scorer import FEATURE_COLS
        for col in FEATURE_COLS:
            vals = [float(p.get(col) or 0) for p in providers]
            feat_means[col] = (sum(vals) / len(vals)) if vals else 0.0

    # NOTE (candidate-engine / case-ledger separation): the Fraud Brain score is
    # a pure function of billing/fraud/data signals — disposition never alters a
    # computed SCORE. MEMBERSHIP is a different matter (Dave's rule): three
    # kinds of provider are excluded from the ranking entirely and receive NO
    # brain rank, same as OIG-excluded providers:
    #   - REPORTED cases (queue_status referred / legacy tip_filed): the work is
    #     done — filed with OIG + referred to MFCU. A membership gate, not a
    #     score input: nothing here changes any remaining provider's score.
    #   - STALE providers (last claim >24mo behind the newest data): not an
    #     active scheme.
    #   - EXPIRED providers (last claim past the ~6yr FCA recovery window):
    #     neither active nor recoverable.
    # Excluded counts are reported in the result so the board can say what was
    # gated. Providers with no parseable claim months are kept (can't prove
    # staleness). Dismissed cases still rank (they're hidden by the queue gate
    # and the board's Actionable view, and their labels train the model).
    from core.review_store import get_queue_statuses
    _reported = {
        n for n, s in get_queue_statuses([p.get("npi") for p in providers if p.get("npi")]).items()
        if s in ("referred", "tip_filed")
    }
    newest_idx = dataset_newest_month_index()
    excluded_counts = {"reported": 0, "stale": 0, "expired": 0}

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

    # within-cohort billing INTENSITY (revenue per beneficiary), same buckets —
    # powers the single most defensible, investigator-ready statement: "bills Nx
    # the {specialty} median per patient".
    cohort_rpb: dict[str, list[float]] = defaultdict(list)
    for p in providers:
        _b = float(p.get("total_beneficiaries") or 0)
        if _b > 0:
            cohort_rpb[_cohort_key(p)].append(float(p.get("total_paid") or 0) / _b)
    for arr in cohort_rpb.values():
        arr.sort()

    scored: list[dict] = []
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue

        # OIG-excluded providers belong on the Excluded page, not the candidate
        # ranking. This is a federal-LEIE *data* filter, independent of any
        # review-queue decision (which must not steer the candidate engine).
        oig = is_excluded(npi)[0]
        if oig:
            continue

        # Membership gates (see the note above): reported / expired / stale
        # providers are NOT ranked at all.
        if npi in _reported:
            excluded_counts["reported"] += 1
            continue
        _age = months_since(p.get("last_month"))
        if _age is not None and _age > FCA_RECOVERY_WINDOW_MONTHS:
            excluded_counts["expired"] += 1
            continue
        _lm_idx = _ym_index(p.get("last_month"))
        if _lm_idx is not None and newest_idx is not None and (newest_idx - _lm_idx) > RECENCY_AGING_MONTHS:
            excluded_counts["stale"] += 1
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
                    driver = _ml_driver_text(p, ml.get("feature_importances"), feat_means)
                    detail = (f"Isolation Forest score {ml_score:.0f}/100 "
                              f"({ml.get('ml_percentile', 0):.0f}th percentile)")
                    if driver:
                        detail += f" — most unusual on {driver}"
                    evidence.append({
                        "source": "ML anomaly detection",
                        "detail": detail,
                        "points": round(ml_component, 1),
                    })
        components["ml_anomaly"] = ml_component

        # 3. Corroborating claim-level analyses
        corr_sources = corroboration.get(npi, [])
        is_org = _is_org_specialty(p.get("specialty"))
        corr_raw = 0.0
        for s in corr_sources:
            # Single-clinician billing-behavior signals (impossible volume,
            # modifier-25 combos, surgical-in-office) are meaningless for an
            # organizational NPI — a hospital/lab/agency legitimately exhibits
            # all of them. Don't let them corroborate fraud for orgs. The
            # underlying detectors over-fire here until the next rescore gates
            # them. Unbundling is excluded (labs unbundling panels is real).
            if s in _INDIVIDUAL_ONLY_SOURCES and is_org:
                continue
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

        # 4b. Within-specialty billing intensity — the most defensible single
        #     statement an investigator can act on. Pure context (0 points): the
        #     intensity is already scored via the ML revenue-per-bene feature and
        #     the cohort-normalized rule signal; this just states it in plain
        #     terms ("bills Nx the specialty median per patient").
        benes = float(p.get("total_beneficiaries") or 0)
        if benes > 0:
            rpb = total_paid / benes
            iarr = cohort_rpb.get(ck) or []
            if len(iarr) >= 20:
                imed = iarr[len(iarr) // 2]
                ipct = bisect.bisect_left(iarr, rpb) / len(iarr) * 100
                if ipct >= 90 and imed > 0 and rpb >= 2 * imed:
                    evidence.append({
                        "source": "Billing intensity (within specialty)",
                        "detail": f"Bills ${rpb:,.0f} per patient — {rpb / imed:.0f}x the "
                                  f"{ck} median of ${imed:,.0f} (top {max(round(100 - ipct), 1)}% "
                                  f"of {len(iarr):,} peers)",
                        "points": 0,
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
        # Dampening is size-vs-signal only. Review-queue disposition (e.g.
        # "confirmed") deliberately does NOT rescue a provider here — case
        # decisions must not steer the candidate ranking (see the note above).
        # OIG providers were already filtered out above, so the only remaining
        # size-independent consideration is the provider's own signal profile.
        dampened = is_institutional
        if dampened:
            score *= INSTITUTIONAL_DAMPEN
            evidence.append({
                "source": "Size adjustment",
                "detail": "Large institutional provider with no provider-specific "
                          "fraud signal beyond scale — score dampened to avoid "
                          "crowding out smaller anomalies",
                "points": 0,
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
            "oig_excluded": oig,  # always False here (OIG providers filtered above)
            # Data recency — from the scan-time SQL aggregate on the cached row.
            # Deliberately NOT a scoring input (see module note): brain_score is
            # unchanged; these ride alongside so triage can see at a glance
            # whether the outlier is still active without a per-NPI timeline pull.
            "first_active_month": p.get("first_month") or None,
            "last_active_month": p.get("last_month") or None,
            "data_age_months": months_since(p.get("last_month")),
            "deactivated_npi": bool(deact_date),
            "size_dampened": dampened,
            "corroborating_sources": len(corr_sources),
            "components": {k: round(v, 1) for k, v in components.items()},
            "evidence": sorted(evidence, key=lambda e: -e["points"]),
        })

    scored.sort(key=lambda x: (-x["brain_score"], -x["total_paid"]))

    # Recency badge, relative to the newest claim month on the board (dataset
    # max) — see the module note on why not wall-clock. Pure annotation; never
    # affects brain_score or ordering.
    dataset_max = max(
        (i for i in (_ym_index(e["last_active_month"]) for e in scored) if i is not None),
        default=None,
    )
    for e in scored:
        e["recency"] = recency_badge(e["last_active_month"], dataset_max)

    # ── One-way read: attach case-ledger status as a READ-ONLY display badge ───
    # The candidate engine reads queue_status here purely to annotate results
    # (so the UI can show "under review" / "tip filed" / "dismissed" and
    # optionally de-prioritise already-actioned providers). This never wrote,
    # and never fed, the score above — scoring finished before this line.
    from core.review_store import get_queue_statuses
    _ledger = get_queue_statuses([e["npi"] for e in scored])
    for e in scored:
        e["queue_status"] = _ledger.get(e["npi"])  # None => not in the review queue

    return {
        "top": scored[:limit],
        "providers_evaluated": len(scored),
        # Membership gates (not score inputs): providers excluded from the
        # ranking entirely — reported (work done), stale (not active), expired
        # (past the recovery window). They receive no brain rank.
        "excluded": excluded_counts,
        "ml_model_used": ml_trained,
        "supervised_model_used": sup_active,
        "corroborated_providers": len(corroboration),
        "weights": {
            # Pure signal weights — the Brain score is a function of these only.
            # Review-queue disposition (confirmed / tip_filed / …) is intentionally
            # NOT a scoring input, so no confirmed-fraud or case-driven boost
            # appears here anymore.
            "rule_signals": W_RULE_SIGNALS, "ml_anomaly": W_ML_ANOMALY,
            "corroboration": W_CORROBORATION, "dollars_at_risk": W_DOLLARS,
            "flag_breadth": W_FLAG_BREADTH,
        },
        "computed_in_ms": int((time.time() - t0) * 1000),
        "computed_at": time.time(),
    }


def _apply_live_ledger(entries: list[dict]) -> list[dict]:
    """Re-check the case ledger on every CACHED serve: a provider Dave just
    marked Reported (or archived) must vanish from the board immediately, not
    after the 15-min TTL. Cheap (one in-memory dict read); returns fresh copies
    with up-to-date queue_status and newly-reported/archived rows dropped —
    the same membership rule compute_top_frauds applies at compute time."""
    from core.review_store import get_queue_statuses
    statuses = get_queue_statuses([e["npi"] for e in entries])
    out = []
    for e in entries:
        qs = statuses.get(e["npi"])
        if qs in ("referred", "tip_filed", "archived"):
            continue
        out.append({**e, "queue_status": qs})
    return out


def get_top_frauds(limit: int = 10, force_refresh: bool = False) -> dict:
    """TTL-cached wrapper around compute_top_frauds."""
    with _lock:
        cached = _cache["result"]
        fresh = (time.time() - _cache["computed_at"]) < CACHE_TTL_SEC
    if cached and fresh and not force_refresh:
        live = _apply_live_ledger(cached["top"])
        if len(live) >= limit:
            return {**cached, "top": live[:limit], "cached": True}
        # Too few rows survive the live ledger check — fall through to recompute.

    # Defense-in-depth: never serve OR cache a ranking computed while the OIG
    # exclusion store is empty. On a cold start that store loads at startup /
    # downloads from HHS; a compute in that window buries provable fraud
    # (excluded providers dark, no OIG boost) and produces a wildly different
    # board — different NPIs, missing names, wrong scores. If that garbage board
    # reaches the client it gets cached there and disagrees with the warm board
    # the Fraud Brain page later shows. So while OIG is warming, prefer the last
    # good cached board (stale-but-complete beats fresh-but-incomplete).
    from core.oig_store import get_oig_stats
    oig_ready = get_oig_stats().get("record_count", 0) > 0
    if not oig_ready and cached and len(cached.get("top", [])) >= limit:
        return {**cached, "top": _apply_live_ledger(cached["top"])[:limit], "cached": True, "warming": True}

    result = compute_top_frauds(limit=max(limit, 25))  # compute a few extra for cheap re-serves

    if oig_ready:
        with _lock:
            _cache["result"] = result
            _cache["computed_at"] = time.time()
    # No prior board to fall back on (truly cold first request) — serve this one
    # but flag it so callers know the reference stores are still loading.
    return {**result, "top": result["top"][:limit], "cached": False, "warming": not oig_ready}
