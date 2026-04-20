"""
Fraud signal detectors — grounded in OIG/CMS enforcement methodology.

Each function accepts a provider aggregate dict plus optional extra data and
returns a SignalResult (score 0.0–1.0, weight, reason, flagged flag).

Signal weights (original 8 sum to 100; new signals 9–12 add bonus weight,
composite is capped at 100 by min(composite, 100) in the scorer):

  billing_concentration          15  — single-code dominance (OIG concentration analysis)
  revenue_per_bene_outlier       20  — revenue z-score vs. same-code peers (OIG statistical method)
  claims_per_bene_anomaly        15  — claims volume z-score vs. all providers (OIG statistical method)
  billing_ramp_rate              15  — explosive growth + large absolute dollars (OIG new-provider screen)
  bust_out_pattern               15  — peak-then-exit pattern (documented in OIG enforcement actions)
  ghost_billing                   5  — CMS 12-beneficiary suppression floor abuse
  total_spend_outlier            10  — total payments z-score vs. all providers (OIG #1 predictor)
  billing_consistency             5  — unnaturally flat monthly billing (OIG automated-claims flag)
  bene_concentration              8  — extremely high claims-per-bene ratio / phantom billing
  upcoding_pattern               10  — concentration on highest-value codes vs. peers
  address_cluster_risk            5  — 3+ providers sharing same physical address
  oig_excluded                   10  — provider on OIG LEIE exclusion list (automatic full score)
  specialty_mismatch              8  — billing outside NPPES taxonomy specialty (cross-specialty fraud)
  corporate_shell_risk            7  — one authorized official controlling 3+ billing NPIs
  geographic_impossibility        6  — NPPES state vs. billing state mismatch (cross-state fraud)
  dead_npi_billing               10  — deactivated NPI with billing activity (identity theft)
  new_provider_explosion          7  — newly enumerated NPI with disproportionately high billing
  ghost_employee_billing         10  — servicing NPI is excluded/deactivated (identity theft)
  servicing_npi_concentration     6  — 95%+ of billing through one rendering NPI
  beneficiary_sharing_anomaly     8  — abnormal patient overlap with another provider
  pecos_enrollment_gap            5  — no Medicare enrollment (Medicaid-only provider)
  reassignment_chain_depth        6  — unusually many NPIs billing through one group

Total possible weight: 206. The min(composite, 100) cap in the scorer handles overflow.

References:
  OIG Medicaid Fraud Control Units Annual Report FY2024
  CMS Fraud Prevention System methodology
  42 CFR Part 455 (program integrity requirements)
  OIG Work Plan statistical anomaly detection guidance
"""
from __future__ import annotations
import math
from datetime import datetime, date
from typing import TypedDict


class SignalResult(TypedDict):
    signal: str
    score: float        # 0.0 – 1.0
    weight: int
    reason: str
    flagged: bool
    data_quality: str   # "full", "partial", or "none" — indicates data completeness


# ── 1. Billing concentration ─────────────────────────────────────────────────
def billing_concentration(provider: dict, hcpcs_rows: list[dict]) -> SignalResult:
    """
    Flag when a single HCPCS code dominates billing (>80% of total paid).

    OIG basis: Providers that bill almost entirely for one procedure code —
    especially high-risk codes like personal care services (T1019, S5125),
    home health (G0299, G0300), or DME — are a top enforcement target.
    Legitimate providers serving broad patient needs bill a mix of codes.

    Threshold raised from an arbitrary 70% to 80% to reduce false positives
    on legitimate specialists who naturally concentrate on fewer codes.
    """
    total = sum(r["total_paid"] for r in hcpcs_rows) or 1
    top = max(hcpcs_rows, key=lambda r: r["total_paid"], default=None)
    if not top:
        return _result("billing_concentration", 0.0, 15, "No HCPCS data", False, "none")

    pct = top["total_paid"] / total
    flagged = pct > 0.80
    score = min(max(pct - 0.80, 0) / 0.20, 1.0) if pct > 0.50 else 0.0
    reason = (
        f"{top['hcpcs_code']} represents {pct:.0%} of billing — single-code dominance"
        if flagged
        else f"Top code {top['hcpcs_code']} at {pct:.0%} (no single-code dominance)"
    )
    return _result("billing_concentration", score, 15, reason, flagged)


# ── 2. Revenue-per-beneficiary outlier ───────────────────────────────────────
def revenue_per_bene_outlier(
    provider: dict,
    peer_mean: float,
    peer_std: float,
) -> SignalResult:
    """
    Z-score of this provider's revenue_per_beneficiary vs. providers billing
    the same top HCPCS code (same-service peer group).

    OIG basis: Comparing revenue per beneficiary against a peer group of
    providers delivering the same service type is core OIG statistical
    methodology. Flagging at >3σ matches the industry-standard definition
    of a statistical outlier and is the threshold used in CMS Comparative
    Billing Reports.
    """
    rpb = provider.get("revenue_per_beneficiary") or 0.0
    if peer_std == 0:
        return _result("revenue_per_bene_outlier", 0.0, 20, "Insufficient peer data", False, "partial")

    z = (rpb - peer_mean) / peer_std
    flagged = z > 3.0
    score = min(max(z - 3.0, 0) / 3.0, 1.0) if z > 0 else 0.0
    reason = (
        f"Revenue/beneficiary ${rpb:,.0f} is {z:.1f}σ above peers (mean ${peer_mean:,.0f})"
        if flagged
        else f"Revenue/beneficiary ${rpb:,.0f} within normal range (z={z:.2f})"
    )
    return _result("revenue_per_bene_outlier", score, 20, reason, flagged)


# ── 3. Claims-per-beneficiary anomaly ────────────────────────────────────────
def claims_per_bene_anomaly(
    provider: dict,
    peer_mean: float = 0.0,
    peer_std: float = 0.0,
) -> SignalResult:
    """
    Total claims per unique beneficiary, compared statistically against all
    scanned providers (z-score > 3σ).

    OIG basis: OIG enforcement cases document extreme examples — 312 claims
    per beneficiary in a single year (nearly one per day), or 48 claims/month
    when peers average 4. The threshold must be data-driven because legitimate
    rates vary hugely by service type: a home health agency will naturally have
    higher ratios than a specialist. Comparing against the peer distribution
    of ALL providers in the dataset is the OIG-endorsed approach.

    Fallback threshold of 100 claims/beneficiary is used when fewer than 3
    providers have been scanned (OIG documented real fraud cases exceeding
    this absolute level regardless of peer group).
    """
    cpb = provider.get("claims_per_beneficiary") or 0.0

    if peer_std > 0:
        z = (cpb - peer_mean) / peer_std
        flagged = z > 3.0
        score = min(max(z - 3.0, 0) / 3.0, 1.0) if z > 0 else 0.0
        reason = (
            f"{cpb:.1f} claims/beneficiary is {z:.1f}σ above peer mean ({peer_mean:.1f})"
            if flagged
            else f"{cpb:.1f} claims/beneficiary within normal range (z={z:.2f}, mean={peer_mean:.1f})"
        )
    else:
        flagged = cpb > 100.0
        score = min(max(cpb - 100.0, 0) / 100.0, 1.0) if cpb > 50.0 else 0.0
        reason = (
            f"{cpb:.1f} claims/beneficiary exceeds absolute limit of 100 (no peer data yet)"
            if flagged
            else f"{cpb:.1f} claims/beneficiary (insufficient peer data for z-score)"
        )

    return _result("claims_per_bene_anomaly", score, 15, reason, flagged)


# ── 4. Billing ramp rate ──────────────────────────────────────────────────────
def billing_ramp_rate(timeline: list[dict]) -> SignalResult:
    """
    Explosive billing growth in a provider's first 6 months, requiring both
    a large percentage increase AND a meaningful absolute dollar amount.

    OIG basis: Ramp-up fraud is well-documented — new providers (especially
    home health, DME, personal care) rapidly inflate billing before
    investigators can respond. OIG flags providers with year-over-year growth
    >200% combined with large absolute dollar jumps. The absolute threshold
    ($50K in month 6) prevents false positives on micro-providers where a
    large percentage change means little in dollar terms.
    """
    if len(timeline) < 6:
        return _result("billing_ramp_rate", 0.0, 15, "Fewer than 6 months of history", False, "partial")

    start   = timeline[0]["total_paid"] or 0
    end_val = timeline[5]["total_paid"] or 0

    # Require meaningful absolute dollars — OIG focuses on providers billing at scale
    if end_val < 50_000:
        return _result(
            "billing_ramp_rate", 0.0, 15,
            f"Month-6 billing ${end_val:,.0f} too small to be meaningful (< $50K)", False,
        )

    if start == 0:
        pct = float("inf")
        flagged = True
        score = 1.0
        reason = f"Billing jumped from $0 to ${end_val:,.0f} in 6 months"
    else:
        pct = (end_val - start) / start * 100
        abs_change = end_val - start
        # OIG criteria: large % growth AND large absolute change
        flagged = pct > 400 and abs_change >= 50_000
        score = min(max(pct - 400, 0) / 600.0, 1.0) if pct > 200 else 0.0
        reason = (
            f"Billing grew {pct:.0f}% (${abs_change:,.0f} absolute) in first 6 months"
            if flagged
            else f"Billing ramp {pct:.0f}% in first 6 months (normal)"
        )
    return _result("billing_ramp_rate", score, 15, reason, flagged)


# ── 5. Bust-out pattern ───────────────────────────────────────────────────────
def bust_out_pattern(timeline: list[dict]) -> SignalResult:
    """
    Peak billing followed by 3+ consecutive months of near-zero activity,
    then no return to previous volumes.

    OIG basis: The "ramp and exit" signature appears repeatedly in OIG
    enforcement actions. Fraudulent providers (particularly DME suppliers,
    home health agencies, personal care providers) bill aggressively, then
    abruptly stop — either because they've been caught, excluded, or have
    moved on to a new entity. Legitimate providers that stop billing typically
    close gradually or transfer patients.
    """
    if len(timeline) < 4:
        return _result("bust_out_pattern", 0.0, 15, "Insufficient history", False, "partial")

    values = [r["total_paid"] for r in timeline]
    peak_idx = max(range(len(values)), key=lambda i: values[i])
    peak_val = values[peak_idx]

    if peak_val == 0:
        return _result("bust_out_pattern", 0.0, 15, "No billing activity", False)

    post_peak = values[peak_idx + 1:]
    silence_streak = 0
    for v in post_peak:
        if v == 0 or v is None:
            silence_streak += 1
        else:
            silence_streak = 0

    flagged = silence_streak >= 3
    score = min(silence_streak / 6.0, 1.0) if silence_streak >= 3 else 0.0
    reason = (
        f"Peak billing ${peak_val:,.0f} followed by {silence_streak} months of $0 — bust-out pattern"
        if flagged
        else "No bust-out pattern detected"
    )
    return _result("bust_out_pattern", score, 15, reason, flagged)


# ── 6. Ghost billing ──────────────────────────────────────────────────────────
def ghost_billing(provider: dict, timeline: list[dict]) -> SignalResult:
    """
    Billing with revenue > $0 but beneficiary count consistently at exactly
    12 — the CMS data suppression floor for privacy protection.

    OIG basis: CMS suppresses exact beneficiary counts when fewer than 11
    unique beneficiaries received a service, replacing the count with 12.
    When a provider consistently shows exactly 12 beneficiaries across many
    months with non-zero payments, it may indicate fabricated claims designed
    to remain just below detection thresholds. This pattern has appeared in
    OIG phantom billing investigations.
    """
    if not timeline:
        return _result("ghost_billing", 0.0, 5, "No timeline data", False, "none")

    ghost_months = sum(
        1 for r in timeline
        if (r.get("total_paid") or 0) > 0 and (r.get("total_unique_beneficiaries") or 0) == 12
    )
    total_months = len(timeline)
    ghost_pct = ghost_months / total_months if total_months else 0

    flagged = ghost_pct > 0.5 and total_months >= 6
    score = min(ghost_pct, 1.0) if flagged else 0.0
    reason = (
        f"{ghost_months}/{total_months} billing months show exactly 12 beneficiaries "
        f"(CMS suppression floor — possible phantom billing)"
        if flagged
        else f"{ghost_months}/{total_months} months at suppression floor (not flagged)"
    )
    return _result("ghost_billing", score, 5, reason, flagged)


# ── 7. Total spend outlier ────────────────────────────────────────────────────
def total_spend_outlier(
    provider: dict,
    peer_mean: float = 0.0,
    peer_std: float = 0.0,
) -> SignalResult:
    """
    Total Medicaid payments compared statistically against all scanned providers.

    OIG basis: Absolute spending level is the single strongest predictor in OIG
    machine learning models trained on excluded/sanctioned providers. Major fraud
    cases almost universally involve providers billing far above the peer median.
    The OIG's own published data shows the largest cases involved providers
    billing 3–10× the peer mean for their service type.

    Uses z-score >3σ (same threshold as revenue_per_bene_outlier) so the flag
    adapts to the real distribution of your dataset rather than a fixed dollar
    amount (which would be meaningless across different service types and states).
    """
    total = provider.get("total_paid") or 0.0
    if peer_std == 0:
        return _result("total_spend_outlier", 0.0, 10, "Insufficient peer data", False, "partial")

    z = (total - peer_mean) / peer_std
    flagged = z > 3.0
    score = min(max(z - 3.0, 0) / 3.0, 1.0) if z > 0 else 0.0
    reason = (
        f"Total paid ${total:,.0f} is {z:.1f}σ above peer mean (${peer_mean:,.0f})"
        if flagged
        else f"Total paid ${total:,.0f} within normal range (z={z:.2f}, mean=${peer_mean:,.0f})"
    )
    return _result("total_spend_outlier", score, 10, reason, flagged)


# ── 8. Billing consistency anomaly ───────────────────────────────────────────
def billing_consistency(provider: dict, timeline: list[dict]) -> SignalResult:
    """
    Unnaturally consistent monthly billing — coefficient of variation (CV) < 0.15
    across at least 12 active months.

    OIG basis: Legitimate providers have natural monthly variation due to patient
    mix, seasonality, staff changes, and service delivery realities. A CV below
    0.15 (standard deviation less than 15% of the mean) across a full year of
    billing is a documented OIG flag for automated or manufactured claims —
    essentially, billing that looks computer-generated rather than service-driven.
    This pattern appeared in OIG investigations of personal care service fraud
    where providers billed identical amounts every single month.

    Requires 12+ months with >0 billing to be statistically meaningful.
    """
    if len(timeline) < 12:
        return _result(
            "billing_consistency", 0.0, 5,
            f"Only {len(timeline)} billing months (need 12+ for consistency analysis)", False,
        )

    nonzero = [r.get("total_paid") or 0 for r in timeline if (r.get("total_paid") or 0) > 0]
    if len(nonzero) < 12:
        return _result(
            "billing_consistency", 0.0, 5,
            f"Only {len(nonzero)} non-zero billing months (need 12+)", False,
        )

    mean = sum(nonzero) / len(nonzero)
    if mean == 0:
        return _result("billing_consistency", 0.0, 5, "Zero mean billing", False)

    variance = sum((v - mean) ** 2 for v in nonzero) / len(nonzero)
    cv = math.sqrt(variance) / mean

    flagged = cv < 0.15
    score = min(max(0.15 - cv, 0) / 0.15, 1.0) if cv < 0.15 else 0.0
    reason = (
        f"Monthly billing CV={cv:.3f} — unnaturally consistent (threshold < 0.15), "
        f"suggests automated or manufactured claims"
        if flagged
        else f"Monthly billing CV={cv:.2f} — natural variation present (normal)"
    )
    return _result("billing_consistency", score, 5, reason, flagged)


# ── 9. Beneficiary co-concentration ──────────────────────────────────────
def bene_concentration(provider: dict) -> SignalResult:
    """
    Flag providers with an extremely high claims-to-beneficiary ratio (>15
    claims per unique beneficiary), or a phantom billing pattern (few
    beneficiaries but many claims).

    OIG basis: Phantom billing — fabricating services for a small pool of
    beneficiaries — produces abnormally high claims-per-beneficiary ratios.
    OIG enforcement cases document providers billing 20–50+ services per
    beneficiary per year when peers average 3–5. A separate check catches
    a related pattern: very few beneficiaries (< 20) with high total claims
    (> 200), which suggests a provider is cycling claims through a handful
    of real or stolen beneficiary IDs.
    """
    total_claims = provider.get("total_claims") or 0
    total_bene = (
        provider.get("total_beneficiaries")
        or provider.get("total_unique_beneficiaries")
        or 0
    )

    if total_bene == 0:
        if total_claims > 0:
            return _result(
                "bene_concentration", 1.0, 8,
                f"{total_claims} claims with 0 beneficiaries — possible phantom billing",
                True,
            )
        return _result("bene_concentration", 0.0, 8, "No claims data", False, "none")

    ratio = total_claims / total_bene

    # Pattern 1: Very few beneficiaries with lots of claims (phantom billing)
    phantom = total_bene < 20 and total_claims > 200
    # Pattern 2: Extremely high claims-per-bene ratio
    high_ratio = ratio > 15

    flagged = phantom or high_ratio

    if phantom and high_ratio:
        score = min(ratio / 30.0, 1.0)
        reason = (
            f"{total_claims} claims across only {total_bene} beneficiaries "
            f"({ratio:.1f} claims/bene) — phantom billing pattern"
        )
    elif phantom:
        score = min(total_claims / 500.0, 1.0)
        reason = (
            f"Only {total_bene} beneficiaries but {total_claims} total claims — "
            f"possible phantom billing"
        )
    elif high_ratio:
        # Scale: 15 = threshold, 30 = max score
        score = min(max(ratio - 15, 0) / 15.0, 1.0)
        reason = f"{ratio:.1f} claims/beneficiary (threshold: 15) — high concentration"
    else:
        score = 0.0
        reason = f"{ratio:.1f} claims/beneficiary — within normal range"

    return _result("bene_concentration", score, 8, reason, flagged)


# ── 10. Upcoding detection ──────────────────────────────────────────────
# HCPCS E/M code families ordered by value (low to high within each family)
_EM_FAMILIES: dict[str, list[str]] = {
    "office_outpatient_new":      ["99201", "99202", "99203", "99204", "99205"],
    "office_outpatient_est":      ["99211", "99212", "99213", "99214", "99215"],
    "inpatient_initial":          ["99221", "99222", "99223"],
    "inpatient_subsequent":       ["99231", "99232", "99233"],
    "ed_visit":                   ["99281", "99282", "99283", "99284", "99285"],
    "home_health_new":            ["99341", "99342", "99343", "99344", "99345"],
    "home_health_est":            ["99347", "99348", "99349", "99350"],
}
# Build reverse lookup: code -> (family_name, rank within family, family size)
_CODE_FAMILY: dict[str, tuple[str, int, int]] = {}
for _fam, _codes in _EM_FAMILIES.items():
    _n = len(_codes)
    for _i, _c in enumerate(_codes):
        _CODE_FAMILY[_c] = (_fam, _i, _n)


def upcoding_pattern(provider: dict, hcpcs_rows: list[dict]) -> SignalResult:
    """
    Detect upcoding — systematically billing higher-value codes within an
    E/M family compared to peers.

    OIG basis: Upcoding (billing a higher-level E/M code than the service
    warrants) is one of the most common forms of Medicaid fraud, documented
    extensively in OIG Work Plans and enforcement actions. The OIG compares
    a provider's distribution of E/M levels against peer distributions for
    the same service type. A provider billing the highest-level code in a
    family at >2x the expected rate is a strong upcoding indicator.

    This implementation checks whether the provider's billing is heavily
    skewed toward the top code(s) in any E/M family present in their HCPCS
    breakdown. If a provider has >50% of their family-specific claims on the
    highest code when the peer average for that code is <25%, that is flagged.
    """
    if not hcpcs_rows:
        return _result("upcoding_pattern", 0.0, 10, "No HCPCS data", False, "none")

    # Build a map of code -> total_claims for this provider
    code_claims: dict[str, float] = {}
    for row in hcpcs_rows:
        code_claims[row["hcpcs_code"]] = float(
            row.get("total_claims") or row.get("total_paid") or 0
        )

    # Check each E/M family the provider bills
    worst_score = 0.0
    worst_reason = ""
    family_found = False

    for fam_name, fam_codes in _EM_FAMILIES.items():
        # Get this provider's claims within this family
        fam_claims = {c: code_claims.get(c, 0) for c in fam_codes}
        fam_total = sum(fam_claims.values())
        if fam_total < 10:  # Need meaningful volume to judge
            continue

        family_found = True
        top_code = fam_codes[-1]  # Highest-value code in the family
        top_pct = fam_claims[top_code] / fam_total if fam_total > 0 else 0

        # Also check second-highest code
        if len(fam_codes) >= 2:
            second_code = fam_codes[-2]
            top2_pct = (fam_claims[top_code] + fam_claims[second_code]) / fam_total
        else:
            top2_pct = top_pct

        # Flag if top code represents >50% of family claims
        # (peer expectation: ~15-25% for the highest code in most families)
        # OR if top two codes represent >80% (severe skew toward high-value end)
        if top_pct > 0.50:
            severity = min((top_pct - 0.50) / 0.30, 1.0)
            if severity > worst_score:
                worst_score = severity
                worst_reason = (
                    f"Upcoding: {top_code} is {top_pct:.0%} of {fam_name} billing "
                    f"(expected <25%) — {fam_total:.0f} total claims in family"
                )
        elif top2_pct > 0.80:
            severity = min((top2_pct - 0.80) / 0.20, 1.0) * 0.7  # Lower severity
            if severity > worst_score:
                worst_score = severity
                worst_reason = (
                    f"Upcoding: top 2 codes ({fam_codes[-1]}, {fam_codes[-2]}) "
                    f"represent {top2_pct:.0%} of {fam_name} billing"
                )

    if not family_found:
        return _result("upcoding_pattern", 0.0, 10, "No E/M code families in billing", False)

    flagged = worst_score > 0
    if not flagged:
        worst_reason = "E/M code distribution within normal range"

    return _result("upcoding_pattern", worst_score, 10, worst_reason, flagged)


# ── 11. Address cluster risk ────────────────────────────────────────────
def address_cluster_risk(provider: dict, address_cluster_size: int) -> SignalResult:
    """
    Flag providers sharing a physical address with 3+ other providers.

    OIG basis: OIG investigations have repeatedly found fraudulent providers
    operating multiple entities from the same address — sometimes dozens of
    NPIs registered to a single suite in a strip mall. While legitimate
    medical buildings do house multiple providers, a cluster of 3+ providers
    at the exact same street address + ZIP code warrants investigation,
    particularly when combined with other fraud signals.

    The cluster size is pre-computed by the caller from NPPES address data
    in the prescan cache (grouping by zip + street).
    """
    if address_cluster_size < 1:
        return _result(
            "address_cluster_risk", 0.0, 5,
            "No NPPES address data available", False, "none",
        )

    flagged = address_cluster_size >= 3
    if flagged:
        # Scale: 3 = minimum flag, 10+ = max score
        score = min(max(address_cluster_size - 3, 0) / 7.0 + 0.3, 1.0)
        reason = (
            f"{address_cluster_size} providers share this address — "
            f"multi-entity cluster (OIG co-location flag)"
        )
    else:
        score = 0.0
        reason = (
            f"{address_cluster_size} provider(s) at this address — "
            f"below cluster threshold (< 3)"
        )

    return _result("address_cluster_risk", score, 5, reason, flagged)


# ── 14. Corporate shell detection ─────────────────────────────────────
def corporate_shell_risk(row: dict, auth_cluster_size: int) -> SignalResult:
    """
    Flag providers whose authorized official controls 3+ NPIs.

    OIG basis: A common fraud scheme involves a single individual registering
    multiple billing entities (NPIs) — each appearing independent but controlled
    by the same authorized official. This "corporate shell" network allows the
    controller to distribute fraudulent billing across entities to stay below
    per-provider detection thresholds. OIG investigations have uncovered
    networks of 5–20+ shell entities under one person, collectively billing
    millions. Grouping NPIs by their NPPES authorized official name reveals
    these hidden networks.

    The cluster size is pre-computed by the caller from NPPES authorized
    official data in the prescan cache.
    """
    if auth_cluster_size < 1:
        return _result(
            "corporate_shell_risk", 0.0, 7,
            "No authorized official data available (individual NPI or no NPPES data)",
            False, "none",
        )
    if auth_cluster_size < 3:
        label = "NPI" if auth_cluster_size == 1 else "NPIs"
        return _result(
            "corporate_shell_risk", 0.0, 7,
            f"Authorized official controls {auth_cluster_size} {label} "
            f"— within normal range",
            False,
        )

    # Scale: (cluster_size - 2) / 8, capped at 1.0
    score = min((auth_cluster_size - 2) / 8.0, 1.0)
    reason = (
        f"Authorized official controls {auth_cluster_size} NPIs "
        f"— potential shell entity network"
    )
    return _result("corporate_shell_risk", score, 7, reason, True)


# ── 15. Geographic impossibility ──────────────────────────────────────

# US state adjacency map (including DC as a pseudo-state)
ADJACENT_STATES: dict[str, list[str]] = {
    "AL": ["FL","GA","MS","TN"], "AK": [], "AZ": ["CA","CO","NM","NV","UT"],
    "AR": ["LA","MO","MS","OK","TN","TX"], "CA": ["AZ","NV","OR"],
    "CO": ["AZ","KS","NE","NM","OK","UT","WY"], "CT": ["MA","NY","RI"],
    "DE": ["MD","NJ","PA"], "FL": ["AL","GA"], "GA": ["AL","FL","NC","SC","TN"],
    "HI": [], "ID": ["MT","NV","OR","UT","WA","WY"], "IL": ["IN","IA","KY","MO","WI"],
    "IN": ["IL","KY","MI","OH"], "IA": ["IL","MN","MO","NE","SD","WI"],
    "KS": ["CO","MO","NE","OK"], "KY": ["IL","IN","MO","OH","TN","VA","WV"],
    "LA": ["AR","MS","TX"], "ME": ["NH"], "MD": ["DE","PA","VA","WV","DC"],
    "MA": ["CT","NH","NY","RI","VT"], "MI": ["IN","OH","WI"],
    "MN": ["IA","ND","SD","WI"], "MS": ["AL","AR","LA","TN"],
    "MO": ["AR","IL","IA","KS","KY","NE","OK","TN"], "MT": ["ID","ND","SD","WY"],
    "NE": ["CO","IA","KS","MO","SD","WY"], "NV": ["AZ","CA","ID","OR","UT"],
    "NH": ["MA","ME","VT"], "NJ": ["DE","NY","PA"], "NM": ["AZ","CO","OK","TX","UT"],
    "NY": ["CT","MA","NJ","PA","VT"], "NC": ["GA","SC","TN","VA"],
    "ND": ["MN","MT","SD"], "OH": ["IN","KY","MI","PA","WV"],
    "OK": ["AR","CO","KS","MO","NM","TX"], "OR": ["CA","ID","NV","WA"],
    "PA": ["DE","MD","NJ","NY","OH","WV"], "RI": ["CT","MA"],
    "SC": ["GA","NC"], "SD": ["IA","MN","MT","ND","NE","WY"],
    "TN": ["AL","AR","GA","KY","MO","MS","NC","VA"], "TX": ["AR","LA","NM","OK"],
    "UT": ["AZ","CO","ID","NM","NV","WY"], "VT": ["MA","NH","NY"],
    "VA": ["DC","KY","MD","NC","TN","WV"], "WA": ["ID","OR"],
    "WV": ["KY","MD","OH","PA","VA"], "WI": ["IA","IL","MI","MN"],
    "WY": ["CO","ID","MT","NE","SD","UT"], "DC": ["MD","VA"],
}

# Geographic regions for coast-to-coast detection (non-adjacent + different region = max score)
_REGIONS: dict[str, str] = {
    "ME": "NE", "NH": "NE", "VT": "NE", "MA": "NE", "RI": "NE", "CT": "NE",
    "NY": "NE", "NJ": "NE", "PA": "NE", "DE": "NE", "MD": "NE", "DC": "NE",
    "VA": "SE", "WV": "SE", "NC": "SE", "SC": "SE", "GA": "SE", "FL": "SE",
    "AL": "SE", "MS": "SE", "TN": "SE", "KY": "SE",
    "OH": "MW", "MI": "MW", "IN": "MW", "IL": "MW", "WI": "MW", "MN": "MW",
    "IA": "MW", "MO": "MW", "ND": "MW", "SD": "MW", "NE": "MW", "KS": "MW",
    "TX": "SW", "OK": "SW", "AR": "SW", "LA": "SW", "NM": "SW", "AZ": "SW",
    "MT": "W", "ID": "W", "WY": "W", "CO": "W", "UT": "W", "NV": "W",
    "WA": "NW", "OR": "NW", "CA": "W",
    "AK": "NW", "HI": "PAC",
}


def _hops_between(state1: str, state2: str) -> int:
    """
    BFS shortest path in the adjacency graph between two states.
    Returns the number of state borders crossed (1 = adjacent, 2 = one state apart, etc.).
    Returns 0 if same state, -1 if unreachable (e.g. HI/AK to continental).
    """
    if state1 == state2:
        return 0
    if state1 not in ADJACENT_STATES or state2 not in ADJACENT_STATES:
        return -1

    from collections import deque
    visited: set[str] = {state1}
    queue: deque[tuple[str, int]] = deque([(state1, 0)])

    while queue:
        current, dist = queue.popleft()
        for neighbor in ADJACENT_STATES.get(current, []):
            if neighbor == state2:
                return dist + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))

    return -1  # unreachable (island states)


def geographic_impossibility(row: dict) -> SignalResult:
    """
    Flag providers whose NPPES registration state differs from their
    Medicaid billing state in a way that is not geographically plausible.

    OIG basis: Medicaid is a state-administered program — providers must be
    enrolled in the state where they deliver services. A provider registered
    in California via NPPES but billing Florida Medicaid (with no adjacent-
    state justification) is a strong indicator of identity theft, address
    fraud, or an out-of-state billing mill. OIG and state MFCUs flag cross-
    state billing anomalies as part of program integrity reviews, and CMS
    Medicaid program integrity guidance specifically identifies multi-state
    billing discrepancies as a fraud indicator.

    Adjacent-state billing is excluded because border providers legitimately
    serve patients across state lines (e.g., a provider in Kansas City, MO
    serving Kansas Medicaid patients).

    Weight: 6
    """
    # Extract NPPES state (provider's registered practice location)
    nppes_state = (
        row.get("nppes", {}).get("address", {}).get("state", "")
        or row.get("state", "")
    ).strip().upper()

    # Extract billing state from scan progress (which Medicaid program the data covers)
    from core.store import get_scan_progress
    progress = get_scan_progress()
    billing_state = (progress.get("state_filter") or "").strip().upper()

    # If no state data available on either side, cannot evaluate
    if not nppes_state or not billing_state:
        return _result(
            "geographic_impossibility", 0.0, 6,
            "Insufficient state data for geographic analysis",
            False, "none",
        )

    # Same state — no issue
    if nppes_state == billing_state:
        return _result(
            "geographic_impossibility", 0.0, 6,
            f"Provider registered in {nppes_state}, billing in {billing_state} — same state",
            False,
        )

    # Check adjacency — border providers are normal
    adjacent = ADJACENT_STATES.get(nppes_state, [])
    if billing_state in adjacent:
        return _result(
            "geographic_impossibility", 0.0, 6,
            f"Provider registered in {nppes_state}, billing in {billing_state} "
            f"— adjacent states (border provider, normal)",
            False,
        )

    # Non-adjacent: compute severity based on distance and region
    hops = _hops_between(nppes_state, billing_state)
    nppes_region = _REGIONS.get(nppes_state, "?")
    billing_region = _REGIONS.get(billing_state, "?")
    different_region = nppes_region != billing_region

    if hops < 0:
        # Unreachable (island to mainland or vice versa) — maximum severity
        score = 1.0
        reason = (
            f"Provider registered in {nppes_state} but billing in {billing_state} "
            f"— geographically unreachable, not adjacent"
        )
    elif different_region:
        # Different region (e.g. NE vs SW, coast-to-coast) — high severity
        score = 1.0
        reason = (
            f"Provider registered in {nppes_state} ({nppes_region}) but billing "
            f"in {billing_state} ({billing_region}) — {hops} states apart, "
            f"different region"
        )
    else:
        # Same region but not adjacent — moderate severity
        score = 0.7
        reason = (
            f"Provider registered in {nppes_state} but billing in {billing_state} "
            f"— {hops} states apart, not adjacent"
        )

    return _result("geographic_impossibility", score, 6, reason, True)


# ── 12. OIG exclusion boost ────────────────────────────────────────────
def oig_excluded(npi: str) -> SignalResult:
    """
    Automatic full-weight flag if the provider is on the OIG LEIE exclusion
    list (List of Excluded Individuals/Entities).

    OIG basis: Providers on the LEIE have been formally excluded from
    participation in all Federal health care programs. Any Medicaid billing
    by an excluded provider is per se fraudulent under 42 USC 1320a-7b.
    This signal uses a binary score — 1.0 if excluded, 0.0 if not — because
    there is no ambiguity or severity gradient.
    """
    from core.oig_store import is_excluded as _is_excluded

    excluded, record = _is_excluded(npi)

    if excluded:
        name = record.get("name", "Unknown") if record else "Unknown"
        excl_date = record.get("excl_date", "unknown date") if record else "unknown date"
        return _result(
            "oig_excluded", 1.0, 10,
            f"Provider {npi} is on OIG LEIE exclusion list "
            f"(excluded {excl_date}, name: {name})",
            True,
        )

    return _result("oig_excluded", 0.0, 10, "Not on OIG exclusion list", False)


# ── 15. Dead NPI billing ─────────────────────────────────────────────────
def dead_npi_billing(row: dict) -> SignalResult:
    """
    Flag providers whose NPI has been deactivated but still show Medicaid
    billing activity in the dataset.

    OIG basis: A deactivated NPI means CMS has taken the provider out of the
    system — the NPI is no longer valid for billing. Any claims submitted
    under a deactivated NPI are per se unauthorized and may indicate identity
    theft (someone using a deceased or retired provider's NPI to submit
    fraudulent claims) or continued billing by an entity that has been
    formally shut down. This pattern appears in OIG investigations of stolen
    identity fraud rings where deactivated NPIs of deceased physicians are
    used to bill millions in fabricated services.
    """
    nppes = row.get("nppes") or {}
    if not nppes:
        return _result(
            "dead_npi_billing", 0.0, 10,
            "No NPPES data available — cannot verify NPI status",
            False, "none",
        )

    status = (nppes.get("status") or "").strip()

    # Check for deactivation — NPPES API returns "A" for active, "D" for
    # deactivated, but some cached entries may have human-readable strings
    is_deactivated = (
        status.upper() == "D"
        or "deactivat" in status.lower()
    )

    # Also check for an explicit deactivation_date field
    deactivation_date = (nppes.get("deactivation_date") or "").strip()
    if deactivation_date and not is_deactivated:
        # Has a deactivation date but status didn't say deactivated —
        # treat the presence of a deactivation date as confirmation
        is_deactivated = True

    if is_deactivated:
        date_info = f", deactivated {deactivation_date}" if deactivation_date else ""
        return _result(
            "dead_npi_billing", 1.0, 10,
            f"NPI deactivated (status: {status or 'D'}{date_info}) but has "
            f"Medicaid billing activity — possible identity theft or "
            f"unauthorized billing",
            True,
        )

    # Active / normal status
    return _result(
        "dead_npi_billing", 0.0, 10,
        f"NPI status: {status or 'active'} — active and valid",
        False,
    )


# ── 16. New provider explosion ───────────────────────────────────────────
def _parse_date_flexible(date_str: str) -> date | None:
    """Parse a date string trying multiple common formats.

    The NPPES API returns dates in various formats depending on the endpoint
    version and whether the data was cached/transformed.  We try the most
    common patterns and fall back gracefully.
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Try ISO and common US formats
    formats = [
        "%Y-%m-%d",       # 2023-01-15
        "%m/%d/%Y",       # 01/15/2023
        "%m-%d-%Y",       # 01-15-2023
        "%Y/%m/%d",       # 2023/01/15
        "%Y%m%d",         # 20230115
        "%d-%b-%Y",       # 15-Jan-2023
        "%b %d, %Y",      # Jan 15, 2023
        "%B %d, %Y",      # January 15, 2023
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    # Last resort: try dateutil if available
    try:
        from dateutil.parser import parse as du_parse
        return du_parse(date_str).date()
    except Exception:
        return None


def new_provider_explosion(row: dict) -> SignalResult:
    """
    Flag newly enumerated providers (NPI issued within 24 months) that have
    disproportionately high billing volumes.

    OIG basis: Fraud mills frequently obtain new NPIs specifically for
    billing fraud. A brand-new provider billing $500K–$1M+ in their first
    year is an extreme statistical outlier — legitimate new practices take
    years to ramp up to those volumes. OIG new-provider screens flag NPIs
    that reach high billing thresholds within their first 12–18 months of
    existence. This complements the billing_ramp_rate signal (which looks at
    month-over-month growth) by looking at the absolute age of the NPI
    itself vs. total lifetime billing.

    Score tiers:
      1.0 — NPI < 12 months old with > $1M total billing
      0.7 — NPI < 18 months old with > $500K total billing
      0.5 — NPI < 12 months old with > $250K total billing
      0.0 — established provider (> 24 months) or low billing
    """
    nppes = row.get("nppes") or {}
    enum_date_str = (nppes.get("enumeration_date") or "").strip()

    if not enum_date_str:
        return _result(
            "new_provider_explosion", 0.0, 7,
            "No enumeration date available — cannot assess provider age",
            False, "none",
        )

    enum_date = _parse_date_flexible(enum_date_str)
    if enum_date is None:
        return _result(
            "new_provider_explosion", 0.0, 7,
            f"Could not parse enumeration date '{enum_date_str}' — skipping",
            False, "partial",
        )

    today = date.today()
    age_days = (today - enum_date).days
    age_months = age_days / 30.44  # average days per month

    total_paid = float(row.get("total_paid") or 0)

    if age_months > 24:
        return _result(
            "new_provider_explosion", 0.0, 7,
            f"NPI enumerated {enum_date_str} ({age_months:.0f} months ago) "
            f"— established provider, not flagged",
            False,
        )

    # NPI is 24 months old or younger — check billing thresholds
    score = 0.0
    assessment = ""

    if total_paid > 1_000_000 and age_months < 12:
        score = 1.0
        assessment = (
            f"extremely suspicious — over $1M billing in first "
            f"{age_months:.0f} months of existence"
        )
    elif total_paid > 500_000 and age_months < 18:
        score = 0.7
        assessment = (
            f"highly suspicious — over $500K billing in first "
            f"{age_months:.0f} months of existence"
        )
    elif total_paid > 250_000 and age_months < 12:
        score = 0.5
        assessment = (
            f"suspicious — over $250K billing in under 12 months "
            f"of existence"
        )
    else:
        assessment = "billing within expected range for provider age"

    flagged = score > 0
    reason = (
        f"NPI enumerated {enum_date_str}, {age_months:.0f} months ago, "
        f"with ${total_paid:,.0f} total billing — {assessment}"
    )

    return _result("new_provider_explosion", score, 7, reason, flagged)


# ── 13. Specialty mismatch ─────────────────────────────────────────────
# Mapping of NPPES taxonomy description keywords (lowercased substring match)
# to HCPCS code prefixes that are considered "within specialty".  If a
# provider's billing contains codes that don't start with any of the listed
# prefixes, that portion is "outside specialty" and potentially fraudulent.
SPECIALTY_HCPCS_MAP: dict[str, list[str]] = {
    "podiatr": ["11719", "11720", "11721", "11730", "11740", "11750", "28"],
    "chiropr": ["98940", "98941", "98942", "98943", "97140"],
    "optometr": ["920", "V25"],
    "dentist": ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"],
    "psychiatr": [
        "908", "909", "H0", "H2",
        "90833", "90834", "90836", "90837", "90838", "90839",
    ],
    "cardiol": [
        "930", "931", "932", "933", "934", "935", "936", "937", "938", "939",
        "93",
    ],
    "dermatol": ["110", "111", "112", "113", "114", "115", "116", "117", "969"],
    "orthop": ["27", "28", "29", "20", "21", "22", "23", "24", "25", "26"],
    "urolog": [
        "500", "501", "502", "503", "504", "505", "506", "507", "508", "509",
        "51", "52", "53", "54", "55",
    ],
    "physical therap": [
        "970", "971", "972", "973", "974", "975", "976", "977", "97",
    ],
    "speech": [
        "925",   # 92507-92508 therapy, 92521-92526 evals, 92550-92599 function tests
        "926",   # 92610-92618 swallowing evaluations
        "920",   # 92002-92014 ophth (shared eval codes)
        "921",   # audiology
        "97129", "97130",  # cognitive function interventions
        "97530", "97535",  # therapeutic activities, self-care training
        "97150",           # group therapy
        "96105",           # assessment of aphasia
        "31575",           # flexible diagnostic laryngoscopy
        "V57",             # rehab procedures
        "S9152",           # speech therapy per visit
    ],
    "occupational therap": ["970", "971", "972", "973", "97"],
}


def specialty_mismatch(row: dict, hcpcs: list[dict]) -> SignalResult:
    """
    Flag providers whose billing falls largely outside the HCPCS codes
    expected for their NPPES taxonomy specialty.

    OIG basis: Cross-specialty billing — e.g., a podiatrist billing
    psychiatric evaluation codes or a chiropractor billing cardiac
    procedures — is a documented fraud pattern in OIG enforcement actions.
    Legitimate providers occasionally bill ancillary codes, but when a
    significant fraction (>30%) of total paid dollars falls outside the
    provider's declared specialty, it warrants investigation.

    The score scales linearly from 0.0 at <=30% outside-specialty billing
    to 1.0 at >=70% outside-specialty billing.
    """
    if not hcpcs:
        return _result("specialty_mismatch", 0.0, 8, "No HCPCS data", False, "none")

    # ── Resolve the provider's taxonomy description ──────────────────────
    # It may be nested under row["nppes"]["taxonomy"]["description"] or
    # at row["nppes"]["taxonomies"][0]["desc"] depending on enrichment.
    nppes = row.get("nppes") or {}
    taxonomy_desc = ""

    # Try the canonical path first
    tax = nppes.get("taxonomy") or {}
    if isinstance(tax, dict):
        taxonomy_desc = tax.get("description") or tax.get("desc") or ""

    # Fallback: taxonomies list (NPPES API returns a list)
    if not taxonomy_desc:
        taxonomies = nppes.get("taxonomies") or []
        if taxonomies and isinstance(taxonomies, list):
            first = taxonomies[0] if isinstance(taxonomies[0], dict) else {}
            taxonomy_desc = first.get("desc") or first.get("description") or ""

    # Fallback: top-level taxonomy_description (some enrichment paths)
    if not taxonomy_desc:
        taxonomy_desc = row.get("taxonomy_description") or ""

    if not taxonomy_desc:
        return _result(
            "specialty_mismatch", 0.0, 8,
            "No NPPES taxonomy description available — cannot assess specialty mismatch",
            False, "none",
        )

    taxonomy_desc = taxonomy_desc.strip().rstrip(",").strip()
    taxonomy_lower = taxonomy_desc.lower()

    # ── Find matching specialty keyword ──────────────────────────────────
    matched_keyword: str | None = None
    valid_prefixes: list[str] = []
    for keyword, prefixes in SPECIALTY_HCPCS_MAP.items():
        if keyword in taxonomy_lower:
            matched_keyword = keyword
            valid_prefixes = prefixes
            break

    if matched_keyword is None:
        return _result(
            "specialty_mismatch", 0.0, 8,
            f"Specialty \"{taxonomy_desc}\" not in mismatch detection map — skipped",
            False,
        )

    # ── Compute % of billing (by total_paid) outside expected prefixes ───
    total_paid = 0.0
    outside_paid = 0.0

    for h in hcpcs:
        paid = float(h.get("total_paid") or 0)
        total_paid += paid
        code = str(h.get("hcpcs_code") or "")
        if not any(code.startswith(pfx) for pfx in valid_prefixes):
            outside_paid += paid

    if total_paid <= 0:
        return _result(
            "specialty_mismatch", 0.0, 8,
            "No paid billing to analyze for specialty mismatch",
            False,
        )

    outside_pct = outside_paid / total_paid

    # ── Score: 0 at <=30%, linear to 1.0 at >=70% ───────────────────────
    flagged = outside_pct > 0.30
    if outside_pct <= 0.30:
        score = 0.0
    else:
        # Linear scale: 30% -> 0.0, 70% -> 1.0
        score = min((outside_pct - 0.30) / 0.40, 1.0)

    if flagged:
        reason = (
            f"Specialty \"{taxonomy_desc}\" (matched: {matched_keyword}) but "
            f"{outside_pct:.0%} of ${total_paid:,.0f} billed outside expected codes — "
            f"cross-specialty billing flag"
        )
    else:
        reason = (
            f"Specialty \"{taxonomy_desc}\" (matched: {matched_keyword}): "
            f"{outside_pct:.0%} of billing outside expected codes (threshold: >30%)"
        )

    return _result("specialty_mismatch", score, 8, reason, flagged)


# ── Address cluster helper ────────────────────────────────────────────────
def compute_address_clusters(extra_providers: list[dict] | None = None) -> dict[str, int]:
    """
    Build a mapping of NPI -> cluster_size from the prescan cache NPPES data.
    Groups providers by normalized (zip + street) from their NPPES addresses.
    Returns {npi: cluster_size} for all providers with address data.

    If *extra_providers* is given (e.g. the current scan batch with freshly-
    fetched NPPES), those are included alongside the cache so first-batch
    providers contribute to cluster detection.
    """
    from core.store import get_prescanned

    addr_groups: dict[str, list[str]] = {}  # "zip|street" -> [npi, ...]
    npi_key: dict[str, str] = {}            # npi -> "zip|street"

    seen_npis: set[str] = set()
    sources = list(get_prescanned())
    if extra_providers:
        sources.extend(extra_providers)

    for p in sources:
        npi = p.get("npi", "")
        if npi in seen_npis:
            continue  # de-dup (extra may overlap with cache)
        seen_npis.add(npi)
        nppes = p.get("nppes") or {}
        addr = nppes.get("address") or {}
        zip_code = (addr.get("zip") or "")[:5].strip()
        street = (addr.get("line1") or "").strip().upper()
        if not zip_code or not street:
            continue
        key = f"{zip_code}|{street}"
        addr_groups.setdefault(key, []).append(npi)
        npi_key[npi] = key

    # Build NPI -> cluster_size lookup
    result: dict[str, int] = {}
    for npi, key in npi_key.items():
        result[npi] = len(addr_groups[key])

    return result


# ── Authorized official cluster helper ───────────────────────────────────
def compute_auth_official_clusters(extra_providers: list[dict] | None = None) -> dict[str, int]:
    """
    Build a mapping of NPI -> cluster_size from the prescan cache NPPES data.
    Groups providers by normalized authorized official name.
    Returns {npi: cluster_size} for all providers with authorized official data.

    If *extra_providers* is given, those are included alongside the cache.
    """
    from core.store import get_prescanned

    name_groups: dict[str, list[str]] = {}  # "NORMALIZED NAME" -> [npi, ...]
    npi_key: dict[str, str] = {}            # npi -> "NORMALIZED NAME"

    seen_npis: set[str] = set()
    sources = list(get_prescanned())
    if extra_providers:
        sources.extend(extra_providers)

    for p in sources:
        npi = p.get("npi", "")
        if npi in seen_npis:
            continue
        seen_npis.add(npi)
        nppes = p.get("nppes") or {}
        auth_official = nppes.get("authorized_official") or {}
        name = (auth_official.get("name") or "").strip().upper()
        if not name:
            continue
        name_groups.setdefault(name, []).append(npi)
        npi_key[npi] = name

    # Build NPI -> cluster_size lookup
    result: dict[str, int] = {}
    for npi, name in npi_key.items():
        result[npi] = len(name_groups[name])

    return result


# ── 18. Ghost employee billing ────────────────────────────────────────────
def ghost_employee_billing(
    npi: str,
    servicing_npis: list[dict],
) -> SignalResult:
    """
    Flag billing providers whose servicing/rendering NPIs are deactivated,
    excluded from OIG, or don't exist in NPPES.

    OIG basis: A billing entity submits claims naming a rendering provider
    who is deceased, deactivated, or excluded. This is a documented identity
    theft and ghost employee pattern — the "rendering provider" never
    actually delivered the services.

    Input: list of dicts with {servicing_npi, total_paid, total_claims}
    aggregated from the Parquet servicing NPI column.
    """
    if not servicing_npis:
        return _result(
            "ghost_employee_billing", 0.0, 10,
            "No servicing NPI data available", False, "none",
        )

    from core.oig_store import is_excluded as _oig_check

    total_paid_all = sum(float(s.get("total_paid") or 0) for s in servicing_npis)
    if total_paid_all <= 0:
        return _result("ghost_employee_billing", 0.0, 10, "No servicing payments", False, "none")

    ghost_paid = 0.0
    ghost_details: list[str] = []

    for s in servicing_npis:
        s_npi = s.get("servicing_npi", "")
        if not s_npi or s_npi == npi:
            continue  # self-servicing is normal

        s_paid = float(s.get("total_paid") or 0)

        # Check OIG exclusion for servicing NPI
        excluded, _ = _oig_check(s_npi)
        if excluded:
            ghost_paid += s_paid
            ghost_details.append(f"{s_npi} (OIG excluded, ${s_paid:,.0f})")
            continue

        # Check NPPES status for servicing NPI (from pre-fetched cache)
        # We look for deactivated status in the NPPES cache
        from core.store import get_provider_by_npi
        cached = get_provider_by_npi(s_npi)
        if cached:
            nppes = cached.get("nppes") or {}
            status = (nppes.get("status") or "").strip().upper()
            deact_date = (nppes.get("deactivation_date") or "").strip()
            if status == "D" or deact_date:
                ghost_paid += s_paid
                ghost_details.append(f"{s_npi} (deactivated, ${s_paid:,.0f})")

    ghost_pct = ghost_paid / total_paid_all if total_paid_all > 0 else 0

    if ghost_pct > 0:
        score = min(ghost_pct * 2.0, 1.0)  # 50% ghost billing = max score
        reason = (
            f"${ghost_paid:,.0f} ({ghost_pct:.0%}) of servicing payments to "
            f"excluded/deactivated NPIs: {'; '.join(ghost_details[:3])}"
        )
        return _result("ghost_employee_billing", score, 10, reason, True)

    return _result(
        "ghost_employee_billing", 0.0, 10,
        f"All {len(servicing_npis)} servicing NPIs appear active and not excluded",
        False,
    )


# ── 19. Servicing NPI concentration ──────────────────────────────────────
def servicing_npi_concentration(
    npi: str,
    servicing_npis: list[dict],
) -> SignalResult:
    """
    Flag when a billing NPI routes all claims through one servicing NPI.

    OIG basis: Group practices and facilities bill under an organizational
    NPI-2 and route services through multiple rendering providers. When 95%+
    of a billing entity's claims flow through a single rendering NPI, it may
    indicate a sole practitioner misusing a group NPI (enrollment fraud) or
    a billing mill with a single complicit provider.

    Weight: 6
    """
    if not servicing_npis:
        return _result(
            "servicing_npi_concentration", 0.0, 6,
            "No servicing NPI data available", False, "none",
        )

    # Filter out self-servicing (billing NPI == servicing NPI is normal for NPI-1)
    external = [s for s in servicing_npis if s.get("servicing_npi") != npi]
    if not external:
        return _result(
            "servicing_npi_concentration", 0.0, 6,
            "Provider self-services all claims (individual NPI)", False,
        )

    total_paid = sum(float(s.get("total_paid") or 0) for s in external)
    if total_paid <= 0:
        return _result("servicing_npi_concentration", 0.0, 6, "No external servicing payments", False)

    top = max(external, key=lambda s: float(s.get("total_paid") or 0))
    top_paid = float(top.get("total_paid") or 0)
    top_pct = top_paid / total_paid

    flagged = top_pct > 0.95 and len(external) >= 2
    if flagged:
        score = min((top_pct - 0.90) / 0.10, 1.0)
        reason = (
            f"Servicing NPI {top['servicing_npi']} handles {top_pct:.0%} of "
            f"${total_paid:,.0f} across {len(external)} rendering providers"
        )
    else:
        score = 0.0
        reason = (
            f"Top servicing NPI handles {top_pct:.0%} of external rendering "
            f"({len(external)} servicing NPIs)"
        )

    return _result("servicing_npi_concentration", score, 6, reason, flagged)


# ── 20. Beneficiary sharing anomaly ──────────────────────────────────────
def beneficiary_sharing_anomaly(
    npi: str,
    bene_sharing: list[dict],
) -> SignalResult:
    """
    Flag providers sharing abnormally high beneficiary overlap with other NPIs.

    OIG basis: Two providers sharing 80%+ of their patient panel is a strong
    indicator of kickback schemes, patient steering, or coordinated billing
    fraud. Legitimate referral relationships typically share 5-15% of patients.

    Input: list of {other_npi, shared_bene_count, provider_total_benes}
    """
    if not bene_sharing:
        return _result(
            "beneficiary_sharing_anomaly", 0.0, 8,
            "No beneficiary sharing data available", False, "none",
        )

    # Find the most concerning overlap
    provider_benes = bene_sharing[0].get("provider_total_benes", 0) if bene_sharing else 0
    if provider_benes <= 0:
        return _result(
            "beneficiary_sharing_anomaly", 0.0, 8,
            "No beneficiary count available", False, "none",
        )

    worst_pct = 0.0
    worst_npi = ""
    worst_shared = 0

    for entry in bene_sharing:
        shared = int(entry.get("shared_bene_count", 0))
        other_npi = entry.get("other_npi", "")
        if shared <= 0 or not other_npi:
            continue
        pct = shared / provider_benes
        if pct > worst_pct:
            worst_pct = pct
            worst_npi = other_npi
            worst_shared = shared

    if worst_pct >= 0.60:
        score = min((worst_pct - 0.50) / 0.50, 1.0)
        reason = (
            f"Shares {worst_shared} beneficiaries ({worst_pct:.0%}) with NPI "
            f"{worst_npi} — possible kickback or patient steering"
        )
        return _result("beneficiary_sharing_anomaly", score, 8, reason, True)

    return _result(
        "beneficiary_sharing_anomaly", 0.0, 8,
        f"Highest beneficiary overlap is {worst_pct:.0%} (below 60% threshold)",
        False,
    )


# ── 21. PECOS enrollment gap ────────────────────────────────────────────
def pecos_enrollment_gap(npi: str) -> SignalResult:
    """
    Flag Medicaid providers with no Medicare enrollment (PECOS) record.

    OIG basis: Most legitimate healthcare providers are enrolled in both
    Medicare and Medicaid. A provider actively billing Medicaid but absent
    from the Medicare enrollment system is unusual and may indicate a
    Medicaid-only fraud mill or a provider who was denied/revoked from
    Medicare and pivoted to Medicaid (a known pattern).

    Weight: 5
    """
    from core.pecos_store import is_medicare_enrolled, get_pecos_stats

    stats = get_pecos_stats()
    if not stats.get("loaded") or stats.get("enrolled_npi_count", 0) == 0:
        return _result(
            "pecos_enrollment_gap", 0.0, 5,
            "PECOS data not available — cannot check Medicare enrollment",
            False, "none",
        )

    if is_medicare_enrolled(npi):
        return _result(
            "pecos_enrollment_gap", 0.0, 5,
            "Provider has active Medicare enrollment (PECOS verified)",
            False,
        )

    # Not found in PECOS
    return _result(
        "pecos_enrollment_gap", 0.6, 5,
        "No Medicare enrollment record found — Medicaid-only provider "
        "(unusual for most provider types)",
        True,
    )


# ── 22. Reassignment chain depth ────────────────────────────────────────
def reassignment_chain_depth(npi: str) -> SignalResult:
    """
    Flag group NPIs with unusually deep reassignment chains (many individual
    NPIs billing through one group).

    OIG basis: Legitimate group practices and health systems have reassignment
    chains, but chains of 50+ individuals through a single group NPI are
    common in fraud mills. When combined with other flags (high billing,
    excluded providers), deep chains indicate organized fraud networks.

    Weight: 6
    """
    from core.pecos_store import get_reassignment_depth, get_pecos_stats

    stats = get_pecos_stats()
    if not stats.get("loaded"):
        return _result(
            "reassignment_chain_depth", 0.0, 6,
            "PECOS data not available — cannot check reassignment chains",
            False, "none",
        )

    depth = get_reassignment_depth(npi)

    if depth <= 0:
        # Also check if this NPI is an individual reassigning to groups
        from core.pecos_store import get_reassignment_groups
        groups = get_reassignment_groups(npi)
        if groups:
            return _result(
                "reassignment_chain_depth", 0.0, 6,
                f"Individual NPI — reassigns billing to {len(groups)} group(s)",
                False,
            )
        return _result(
            "reassignment_chain_depth", 0.0, 6,
            "No reassignment chain found (individual provider or no PECOS data)",
            False,
        )

    if depth >= 50:
        score = 1.0
        reason = f"{depth} individuals reassign billing to this group NPI — extremely large chain"
    elif depth >= 25:
        score = 0.6
        reason = f"{depth} individuals reassign billing to this group NPI — large chain"
    elif depth >= 10:
        score = 0.3
        reason = f"{depth} individuals reassign billing to this group NPI — moderate chain"
    else:
        return _result(
            "reassignment_chain_depth", 0.0, 6,
            f"{depth} individuals reassign to this group NPI (normal range)",
            False,
        )

    return _result("reassignment_chain_depth", score, 6, reason, depth >= 10)


# ── Corroboration requirements for proxy signals ─────────────────────────────
# Proxy signals fire on things that are more often legitimate than fraudulent.
# They are only meaningful when the same provider is ALSO flagged for at least
# one corroborating signal.  If none of the listed corroborators are active,
# the proxy signal is suppressed (flagged=False, score=0, reason updated).
#
# This prevents false-flag noise: a medical building with 10 providers is
# not suspicious unless those providers also show billing anomalies.

CORROBORATION_RULES: dict[str, list[str]] = {
    "address_cluster_risk": [
        "billing_concentration", "ghost_billing", "bene_concentration",
        "corporate_shell_risk", "ghost_employee_billing",
    ],
    "corporate_shell_risk": [
        "billing_concentration", "revenue_per_bene_outlier", "oig_excluded",
        "ghost_employee_billing", "dead_npi_billing",
    ],
    "specialty_mismatch": [
        "upcoding_pattern", "billing_concentration", "revenue_per_bene_outlier",
    ],
    "geographic_impossibility": [
        "dead_npi_billing", "oig_excluded", "new_provider_explosion",
        "ghost_employee_billing",
    ],
    "new_provider_explosion": [
        "billing_ramp_rate", "bust_out_pattern", "billing_concentration",
        "bene_concentration",
    ],
    "servicing_npi_concentration": [
        "ghost_employee_billing", "corporate_shell_risk", "billing_concentration",
    ],
    "pecos_enrollment_gap": [
        "new_provider_explosion", "billing_ramp_rate", "billing_concentration",
        "bene_concentration",
    ],
    "reassignment_chain_depth": [
        "ghost_employee_billing", "oig_excluded", "dead_npi_billing",
        "billing_concentration",
    ],
}


def suppress_unsupported_signals(signals: list[SignalResult]) -> list[SignalResult]:
    """
    Post-process signal results: suppress proxy signals that lack corroboration.

    A proxy signal that fired (flagged=True) but has NO corroborating signal
    also flagged on the same provider is downgraded to flagged=False, score=0.
    The original reason is preserved with a prefix explaining the suppression.

    Returns a new list (does not mutate the input).
    """
    # Build set of active (flagged) signal IDs for fast lookup
    active_ids = {s["signal"] for s in signals if s["flagged"]}

    out: list[SignalResult] = []
    for s in signals:
        sid = s["signal"]

        # Only applies to proxy signals that actually fired
        if sid not in CORROBORATION_RULES or not s["flagged"]:
            out.append(s)
            continue

        # Check if any corroborating signal is also flagged
        corroborators = CORROBORATION_RULES[sid]
        active_corroborators = [c for c in corroborators if c in active_ids]

        if active_corroborators:
            # Corroboration found — keep the flag, note which signals support it
            out.append(SignalResult(
                signal=s["signal"],
                score=s["score"],
                weight=s["weight"],
                reason=s["reason"],
                flagged=True,
                data_quality=s["data_quality"],
            ))
        else:
            # No corroboration — suppress the flag
            out.append(SignalResult(
                signal=s["signal"],
                score=0.0,
                weight=s["weight"],
                reason=f"[Suppressed — no corroborating flags] {s['reason']}",
                flagged=False,
                data_quality=s["data_quality"],
            ))

    return out


# ── helpers ───────────────────────────────────────────────────────────────────
def _result(signal: str, score: float, weight: int, reason: str, flagged: bool, data_quality: str = "full") -> SignalResult:
    return SignalResult(
        signal=signal,
        score=round(score, 4),
        weight=weight,
        reason=reason,
        flagged=flagged,
        data_quality=data_quality,
    )
