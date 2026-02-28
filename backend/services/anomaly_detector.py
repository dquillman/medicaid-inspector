"""
Fraud signal detectors — grounded in OIG/CMS enforcement methodology.

Each function accepts a provider aggregate dict plus optional extra data and
returns a SignalResult (score 0.0–1.0, weight, reason, flagged flag).

Signal weights (must sum to 100):
  billing_concentration          15  — single-code dominance (OIG concentration analysis)
  revenue_per_bene_outlier       20  — revenue z-score vs. same-code peers (OIG statistical method)
  claims_per_bene_anomaly        15  — claims volume z-score vs. all providers (OIG statistical method)
  billing_ramp_rate              15  — explosive growth + large absolute dollars (OIG new-provider screen)
  bust_out_pattern               15  — peak-then-exit pattern (documented in OIG enforcement actions)
  ghost_billing                   5  — CMS 12-beneficiary suppression floor abuse
  total_spend_outlier            10  — total payments z-score vs. all providers (OIG #1 predictor)
  billing_consistency             5  — unnaturally flat monthly billing (OIG automated-claims flag)

References:
  OIG Medicaid Fraud Control Units Annual Report FY2024
  CMS Fraud Prevention System methodology
  42 CFR Part 455 (program integrity requirements)
  OIG Work Plan statistical anomaly detection guidance
"""
from __future__ import annotations
import math
from typing import TypedDict


class SignalResult(TypedDict):
    signal: str
    score: float        # 0.0 – 1.0
    weight: int
    reason: str
    flagged: bool


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
        return _result("billing_concentration", 0.0, 15, "No HCPCS data", False)

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
        return _result("revenue_per_bene_outlier", 0.0, 20, "Insufficient peer data", False)

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
        return _result("billing_ramp_rate", 0.0, 15, "Fewer than 6 months of history", False)

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
        return _result("bust_out_pattern", 0.0, 15, "Insufficient history", False)

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
        return _result("ghost_billing", 0.0, 5, "No timeline data", False)

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
        return _result("total_spend_outlier", 0.0, 10, "Insufficient peer data", False)

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


# ── helpers ───────────────────────────────────────────────────────────────────
def _result(signal: str, score: float, weight: int, reason: str, flagged: bool) -> SignalResult:
    return SignalResult(
        signal=signal,
        score=round(score, 4),
        weight=weight,
        reason=reason,
        flagged=flagged,
    )
