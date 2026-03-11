"""
Template-based AI Case Narrative Generator.

Produces investigation-ready prose from structured provider data without
calling any external LLM API.  Output mirrors the format used by OIG
Medicaid Fraud Control Units in referral packages.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from core.store import get_prescanned
from core.review_store import get_review_queue
from core.risk_utils import risk_tier_short as _risk_tier, risk_tier_description as _risk_tier_description


# ── Signal metadata: human-readable names, regulatory citations, OIG context ─

_SIGNAL_META: dict[str, dict] = {
    "billing_concentration": {
        "label": "Billing Concentration",
        "explanation": (
            "A disproportionate share of this provider's total Medicaid reimbursement "
            "derives from a single procedure code. Legitimate providers serving broad "
            "patient needs typically bill across a diversified set of codes. Single-code "
            "dominance is a hallmark of billing mill operations identified in OIG "
            "enforcement actions."
        ),
        "citations": [
            "42 CFR § 455.23 (provider screening and enrollment)",
            "42 U.S.C. § 1320a-7b(a) (False Claims — billing for services not rendered)",
            "OIG Medicaid Fraud Control Units Annual Report FY2024",
        ],
    },
    "revenue_per_bene_outlier": {
        "label": "Revenue Per Beneficiary Outlier",
        "explanation": (
            "The revenue generated per unique Medicaid beneficiary is statistically "
            "anomalous relative to peer providers billing primarily for the same "
            "procedure codes. Elevated per-beneficiary revenue may indicate upcoding, "
            "unbundling, or phantom service delivery."
        ),
        "citations": [
            "42 CFR § 455.14 (State plan requirement for fraud detection)",
            "42 U.S.C. § 1320a-7a (Civil monetary penalties for false claims)",
            "OIG Work Plan — Statistical Anomaly Detection Guidance",
        ],
    },
    "claims_per_bene_anomaly": {
        "label": "Claims Per Beneficiary Anomaly",
        "explanation": (
            "The volume of claims submitted per unique beneficiary exceeds statistical "
            "norms. Excessive per-beneficiary claims volume may indicate service "
            "duplication, phantom billing, or medically unnecessary services."
        ),
        "citations": [
            "42 CFR § 456.3 (Utilization control — State plan requirements)",
            "42 U.S.C. § 1320a-7b(b) (Anti-kickback provisions)",
        ],
    },
    "billing_ramp_rate": {
        "label": "Billing Ramp Rate",
        "explanation": (
            "This provider exhibited an explosive increase in billing volume over a "
            "short period. Rapid billing escalation — particularly when coupled with "
            "a newly enumerated NPI — is a primary screening criterion used by CMS "
            "Fraud Prevention System to identify potential bust-out schemes."
        ),
        "citations": [
            "42 CFR § 455.23 (Temporary moratoria on enrollment of new providers)",
            "CMS Fraud Prevention System (FPS) methodology — ramp-rate screening",
        ],
    },
    "bust_out_pattern": {
        "label": "Bust-Out Pattern",
        "explanation": (
            "Billing data exhibits a characteristic peak-then-exit trajectory. "
            "In documented bust-out fraud schemes, providers rapidly escalate billing "
            "to extract maximum reimbursement before abandoning the practice — a pattern "
            "well-documented in OIG enforcement actions."
        ),
        "citations": [
            "42 U.S.C. § 1320a-7(a) (Mandatory exclusion from Federal health care programs)",
            "OIG Semiannual Report to Congress — bust-out scheme case studies",
        ],
    },
    "ghost_billing": {
        "label": "Ghost Billing / Beneficiary Suppression",
        "explanation": (
            "The reported beneficiary count sits at or near the CMS 12-beneficiary "
            "suppression floor while claim volume or revenue is disproportionately high. "
            "This pattern may indicate manipulation of beneficiary-level data to avoid "
            "detection, or billing for services to phantom beneficiaries."
        ),
        "citations": [
            "42 CFR § 455.18 (Provider disclosure requirements)",
            "42 U.S.C. § 1320a-7b(a)(1) (False statements — material misrepresentation)",
        ],
    },
    "bene_concentration": {
        "label": "Beneficiary Concentration",
        "explanation": (
            "An extremely high claims-per-beneficiary ratio suggests that a small "
            "number of beneficiaries are being billed at an unusually intensive rate. "
            "This may indicate phantom billing, unnecessary services, or patient "
            "captivity schemes."
        ),
        "citations": [
            "42 CFR § 456.3 (Utilization control — State plan requirements)",
            "42 U.S.C. § 1320a-7a (Civil monetary penalties)",
        ],
    },
    "upcoding_pattern": {
        "label": "Upcoding Pattern",
        "explanation": (
            "Billing is concentrated on the highest-reimbursement procedure codes "
            "relative to peer providers. Systematic upcoding — billing for more "
            "expensive services than were actually provided — is one of the most "
            "common forms of Medicaid fraud identified by the OIG."
        ),
        "citations": [
            "31 U.S.C. § 3729 (False Claims Act — treble damages)",
            "42 U.S.C. § 1320a-7a(a)(1) (Civil monetary penalties for upcoding)",
            "OIG Work Plan — Upcoding Detection Methodology",
        ],
    },
    "address_cluster_risk": {
        "label": "Address Cluster Risk",
        "explanation": (
            "Multiple billing providers are registered at the same physical address. "
            "While co-located practices exist legitimately, a high concentration of "
            "billing NPIs at a single address is a known indicator of shell company "
            "fraud and has been cited in numerous OIG prosecutions."
        ),
        "citations": [
            "42 CFR § 455.104 (Disclosure of ownership and control)",
            "42 CFR § 455.106 (Disclosure of business transactions)",
        ],
    },
    "oig_excluded": {
        "label": "OIG Exclusion List Match",
        "explanation": (
            "This provider appears on the OIG List of Excluded Individuals/Entities "
            "(LEIE). Excluded providers are prohibited from participating in any "
            "Federal health care program. Billing by an excluded provider constitutes "
            "a per-item violation subject to civil monetary penalties."
        ),
        "citations": [
            "42 U.S.C. § 1320a-7 (Exclusion of certain individuals and entities)",
            "42 CFR § 1001.1901 (Scope and effect of exclusion)",
            "42 U.S.C. § 1320a-7a (Civil monetary penalties — $100,000 per item)",
        ],
    },
    "specialty_mismatch": {
        "label": "Specialty Mismatch",
        "explanation": (
            "Billing patterns do not align with the provider's enrolled specialty "
            "as recorded in NPPES. Cross-specialty billing may indicate identity "
            "theft, credentialing fraud, or services rendered by unlicensed personnel "
            "billed under a legitimate provider's NPI."
        ),
        "citations": [
            "42 CFR § 455.410 (Provider enrollment screening levels)",
            "42 U.S.C. § 1320a-7b(a)(6) (False statements regarding provider status)",
        ],
    },
    "corporate_shell_risk": {
        "label": "Corporate Shell Risk",
        "explanation": (
            "A single authorized official controls multiple billing NPIs. While "
            "legitimate corporate structures exist, concentrated control of multiple "
            "NPIs is a documented feature of corporate shell fraud schemes used to "
            "multiply billing capacity and obfuscate ownership."
        ),
        "citations": [
            "42 CFR § 455.104 (Disclosure of ownership and control)",
            "42 CFR § 455.106 (Disclosure of business transactions)",
            "42 U.S.C. § 1320a-7b(b) (Anti-kickback statute — corporate arrangements)",
        ],
    },
    "dead_npi_billing": {
        "label": "Deactivated NPI Billing",
        "explanation": (
            "This NPI has been deactivated in the NPPES registry but continues to "
            "appear on Medicaid claims. Billing under a deactivated NPI may indicate "
            "identity theft or deliberate use of abandoned provider credentials to "
            "submit fraudulent claims."
        ),
        "citations": [
            "45 CFR § 162.408 (NPI deactivation procedures)",
            "42 U.S.C. § 1320a-7b(a) (False statements — use of deactivated identifier)",
        ],
    },
    "new_provider_explosion": {
        "label": "New Provider Billing Explosion",
        "explanation": (
            "A newly enumerated NPI is generating billing volume disproportionate "
            "to its operational tenure. OIG has documented that fraudulent providers "
            "frequently establish new NPIs specifically to exploit the enrollment "
            "window before detection systems trigger."
        ),
        "citations": [
            "42 CFR § 455.23 (Temporary moratoria on enrollment of new providers)",
            "CMS Fraud Prevention System — new-provider screening protocol",
        ],
    },
    "geographic_impossibility": {
        "label": "Geographic Impossibility",
        "explanation": (
            "The provider's NPPES-registered practice location is in a different "
            "state from where Medicaid claims are being submitted. While telemedicine "
            "and border-area practices can explain some cross-state billing, a "
            "complete state mismatch warrants investigation for potential identity "
            "fraud or fictitious practice locations."
        ),
        "citations": [
            "42 CFR § 455.410 (Provider enrollment — site visits)",
            "42 U.S.C. § 1320a-7b(a)(1) (False statements — fictitious practice)",
        ],
    },
    "total_spend_outlier": {
        "label": "Total Spend Outlier",
        "explanation": (
            "Total Medicaid payments to this provider are statistically anomalous "
            "relative to the broader provider population. Extreme total spend is "
            "the single strongest predictor of fraud identified in OIG's statistical "
            "methodology and warrants priority review."
        ),
        "citations": [
            "42 CFR § 455.14 (State plan requirement for fraud detection)",
            "OIG Work Plan — Total Spend Outlier Detection",
        ],
    },
    "billing_consistency": {
        "label": "Billing Consistency Anomaly",
        "explanation": (
            "Monthly billing amounts are unnaturally uniform. Legitimate medical "
            "practices exhibit natural variation in monthly claims due to patient "
            "volume fluctuations, seasonal patterns, and practice dynamics. Flat-line "
            "billing is an indicator of automated or template-based claim submission."
        ),
        "citations": [
            "42 CFR § 455.23 (Provider screening requirements)",
            "CMS FPS — automated claims detection algorithm",
        ],
    },
}


def _fmt_currency(amount: float) -> str:
    """Format a number as USD currency string."""
    if amount >= 1_000_000:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def _fmt_number(n: float) -> str:
    """Format a number with commas."""
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.1f}"



# _risk_tier and _risk_tier_description are imported from core.risk_utils


def _review_status_label(status: str) -> str:
    labels = {
        "pending": "pending initial review",
        "assigned": "assigned to an investigator",
        "investigating": "under active investigation",
        "confirmed_fraud": "confirmed as fraudulent activity",
        "referred": "referred to law enforcement",
        "dismissed": "reviewed and dismissed",
    }
    return labels.get(status, status)


def _build_subject_section(provider: dict) -> dict:
    """Section (a): Subject Identification."""
    nppes = provider.get("nppes") or {}
    name = nppes.get("name") or provider.get("provider_name") or f"NPI {provider['npi']}"
    entity_type = nppes.get("entity_type", "")
    entity_label = "organization" if entity_type == "NPI-2" else "individual provider"
    taxonomy = nppes.get("taxonomy") or {}
    specialty = taxonomy.get("description", "healthcare provider")
    address = nppes.get("address") or {}
    addr_parts = []
    if address.get("line1"):
        addr_parts.append(address["line1"])
    city = address.get("city") or provider.get("city", "")
    state = address.get("state") or provider.get("state", "")
    zip_code = address.get("zip", "")
    if city:
        addr_parts.append(city)
    location = ", ".join(addr_parts)
    if state:
        location += f", {state}"
    if zip_code:
        location += f" {zip_code}"

    content = (
        f"This report concerns {name} (NPI: {provider['npi']}), "
        f"a {entity_label} classified as {specialty}"
    )
    if location.strip(", "):
        content += f", located at {location}"
    content += "."

    auth = nppes.get("authorized_official")
    if auth and auth.get("name"):
        content += (
            f" The authorized official on record is {auth['name']}"
        )
        if auth.get("title"):
            content += f", {auth['title']}"
        content += "."

    npi_status = nppes.get("status", "")
    if npi_status and npi_status.lower() != "active":
        content += (
            f" NOTE: The NPI registry status is currently listed as "
            f"\"{npi_status},\" which may indicate deactivation or other "
            f"administrative action."
        )

    return {"title": "Subject Identification", "content": content}


def _build_billing_section(provider: dict) -> dict:
    """Section (b): Billing Summary."""
    total_paid = provider.get("total_paid", 0)
    total_claims = provider.get("total_claims", 0)
    total_bene = provider.get("total_beneficiaries", 0)
    rpb = provider.get("revenue_per_beneficiary", 0)
    cpb = provider.get("claims_per_beneficiary", 0)
    first = provider.get("first_month", "unknown")
    last = provider.get("last_month", "unknown")
    active = provider.get("active_months", 0)
    distinct_hcpcs = provider.get("distinct_hcpcs", 0)

    content = (
        f"During the observation period of {first} through {last} "
        f"({active} active billing months), this provider submitted "
        f"{_fmt_number(total_claims)} claims to Medicaid for total "
        f"reimbursement of {_fmt_currency(total_paid)}, serving "
        f"{_fmt_number(total_bene)} unique beneficiaries across "
        f"{distinct_hcpcs} distinct HCPCS procedure codes."
    )

    content += (
        f"\n\nOn a per-beneficiary basis, average revenue was "
        f"{_fmt_currency(rpb)} per beneficiary with an average of "
        f"{_fmt_number(cpb)} claims per beneficiary."
    )

    if total_claims > 0:
        avg_per_claim = total_paid / total_claims
        content += (
            f" The average reimbursement per claim was "
            f"{_fmt_currency(avg_per_claim)}."
        )

    if active > 0:
        monthly_avg = total_paid / active
        content += (
            f" Monthly billing averaged {_fmt_currency(monthly_avg)}."
        )

    return {"title": "Billing Summary", "content": content}


def _build_risk_section(provider: dict) -> dict:
    """Section (c): Risk Assessment."""
    score = provider.get("risk_score", 0)
    tier = _risk_tier(score)
    tier_desc = _risk_tier_description(score)
    signals = provider.get("signal_results") or []
    flags = [s for s in signals if s.get("flagged")]
    total_signals = len(signals)

    content = (
        f"The composite risk score of {score:.1f} out of 100 places this "
        f"provider in the {tier} risk tier, which {tier_desc}. "
        f"Of the {total_signals} fraud detection signals evaluated, "
        f"{len(flags)} triggered positive findings."
    )

    if flags:
        flag_names = [
            _SIGNAL_META.get(s["signal"], {}).get("label", s["signal"])
            for s in flags
        ]
        content += (
            f"\n\nThe triggered signals are: {'; '.join(flag_names)}."
        )

    return {"title": "Risk Assessment", "content": content}


def _build_signal_findings_section(provider: dict) -> dict:
    """Section (d): Detailed signal findings for each flagged signal."""
    signals = provider.get("signal_results") or []
    flags = [s for s in signals if s.get("flagged")]

    if not flags:
        return {
            "title": "Signal Findings",
            "content": (
                "No fraud detection signals were triggered for this provider. "
                "All 17 evaluated metrics fell within normal parameters."
            ),
        }

    paragraphs = []
    for i, sig in enumerate(flags, 1):
        name = sig.get("signal", "unknown")
        meta = _SIGNAL_META.get(name, {})
        label = meta.get("label", name.replace("_", " ").title())
        explanation = meta.get("explanation", "")
        reason = sig.get("reason", "")
        score = sig.get("score", 0)
        weight = sig.get("weight", 0)

        para = f"Finding {i} — {label}: {reason}"
        if explanation:
            para += f" {explanation}"
        para += (
            f" This signal contributed a raw score of {score:.2f} "
            f"(weight: {weight}) to the composite risk assessment."
        )
        paragraphs.append(para)

    content = "\n\n".join(paragraphs)
    return {"title": "Signal Findings", "content": content}


def _build_patterns_section(provider: dict) -> dict:
    """Section (e): Cross-signal pattern synthesis."""
    signals = provider.get("signal_results") or []
    flags = [s for s in signals if s.get("flagged")]
    flag_names = {s["signal"] for s in flags}

    if len(flags) < 2:
        if len(flags) == 1:
            label = _SIGNAL_META.get(flags[0]["signal"], {}).get(
                "label", flags[0]["signal"]
            )
            return {
                "title": "Patterns of Concern",
                "content": (
                    f"A single signal — {label} — was triggered. While an "
                    f"isolated finding may have a benign explanation, it "
                    f"establishes a basis for targeted review of the "
                    f"corresponding claims data."
                ),
            }
        return {
            "title": "Patterns of Concern",
            "content": (
                "No multi-signal patterns were identified. The provider's "
                "billing profile does not exhibit the correlated anomalies "
                "typically associated with organized fraud schemes."
            ),
        }

    patterns = []

    # Billing mill pattern
    billing_mill_signals = flag_names & {
        "billing_concentration", "revenue_per_bene_outlier",
        "new_provider_explosion", "upcoding_pattern",
    }
    if len(billing_mill_signals) >= 2:
        details = []
        for s in flags:
            if s["signal"] in billing_mill_signals:
                details.append(s.get("reason", ""))
        patterns.append(
            "The combination of "
            + ", ".join(
                _SIGNAL_META.get(n, {}).get("label", n)
                for n in billing_mill_signals
            )
            + " creates a profile consistent with OIG-documented billing "
            "mill schemes, where providers maximize reimbursement through "
            "concentrated, high-volume billing on select procedure codes. "
            "Specific findings: " + "; ".join(d for d in details if d) + "."
        )

    # Identity/shell fraud pattern
    shell_signals = flag_names & {
        "corporate_shell_risk", "address_cluster_risk",
        "dead_npi_billing", "specialty_mismatch",
    }
    if len(shell_signals) >= 2:
        patterns.append(
            "The co-occurrence of "
            + ", ".join(
                _SIGNAL_META.get(n, {}).get("label", n)
                for n in shell_signals
            )
            + " raises concerns about potential identity fraud or corporate "
            "shell structures. This combination has been documented in OIG "
            "enforcement actions involving fictitious providers or hijacked "
            "NPI credentials used to bill through shell entities."
        )

    # Phantom billing pattern
    phantom_signals = flag_names & {
        "ghost_billing", "bene_concentration",
        "claims_per_bene_anomaly",
    }
    if len(phantom_signals) >= 2:
        patterns.append(
            "The intersection of "
            + ", ".join(
                _SIGNAL_META.get(n, {}).get("label", n)
                for n in phantom_signals
            )
            + " suggests potential phantom billing — the submission of claims "
            "for services not actually rendered, or the systematic inflation "
            "of service volume to a captive beneficiary population."
        )

    # Bust-out pattern
    bustout_signals = flag_names & {
        "bust_out_pattern", "billing_ramp_rate",
        "new_provider_explosion",
    }
    if len(bustout_signals) >= 2:
        patterns.append(
            "The presence of both rapid billing escalation and "
            "peak-then-exit indicators is characteristic of a bust-out "
            "fraud scheme. In documented cases, newly enrolled providers "
            "rapidly escalate billing to extract maximum reimbursement "
            "before abandoning the practice and enrolled identity."
        )

    # Geographic/mismatch pattern
    geo_signals = flag_names & {
        "geographic_impossibility", "specialty_mismatch",
    }
    if len(geo_signals) >= 2:
        patterns.append(
            "Both geographic impossibility and specialty mismatch were "
            "detected, which in combination raises significant concerns "
            "about the legitimacy of the provider's enrollment. This "
            "profile is consistent with hijacked credentials or a "
            "fictitious practice location."
        )

    if not patterns:
        # Generic multi-signal summary
        flag_labels = [
            _SIGNAL_META.get(s["signal"], {}).get("label", s["signal"])
            for s in flags
        ]
        patterns.append(
            f"This provider triggered {len(flags)} concurrent signals: "
            f"{', '.join(flag_labels)}. The co-occurrence of multiple "
            f"independent fraud indicators elevates concern beyond what "
            f"any single signal would warrant and suggests a pattern "
            f"requiring closer examination of underlying claims data."
        )

    content = "\n\n".join(patterns)
    return {"title": "Patterns of Concern", "content": content}


def _build_actions_section(provider: dict) -> dict:
    """Section (f): Recommended actions based on risk tier and flags."""
    score = provider.get("risk_score", 0)
    signals = provider.get("signal_results") or []
    flags = [s for s in signals if s.get("flagged")]
    flag_names = {s["signal"] for s in flags}

    actions = []

    if score >= 50:
        actions.append(
            "PRIORITY REFERRAL: Forward this case to the State Medicaid "
            "Fraud Control Unit (MFCU) for full investigation pursuant to "
            "42 CFR § 455.21."
        )
        actions.append(
            "PAYMENT SUSPENSION: Consider initiating a payment suspension "
            "under 42 CFR § 455.23 pending investigation, given the "
            "credible allegation of fraud indicated by the risk score."
        )
    elif score >= 25:
        actions.append(
            "ENHANCED REVIEW: Conduct a detailed claims-level audit of "
            "all submissions from this provider for the flagged period."
        )
        actions.append(
            "PRELIMINARY INVESTIGATION: Assign this case to a program "
            "integrity analyst for comprehensive review before potential "
            "MFCU referral."
        )
    else:
        actions.append(
            "ROUTINE MONITORING: Place this provider on an enhanced "
            "monitoring watch list with quarterly billing pattern reviews."
        )

    # Signal-specific actions
    if "oig_excluded" in flag_names:
        actions.append(
            "IMMEDIATE ACTION — OIG EXCLUSION: Verify exclusion status "
            "against the current LEIE database. If confirmed, immediately "
            "terminate provider participation and initiate overpayment "
            "recovery for all claims paid during the exclusion period "
            "(42 U.S.C. § 1320a-7)."
        )

    if "dead_npi_billing" in flag_names:
        actions.append(
            "NPI VERIFICATION: Confirm NPI status with NPPES. If "
            "deactivated, refer to OIG for potential identity theft "
            "investigation and recover all post-deactivation payments."
        )

    if "geographic_impossibility" in flag_names:
        actions.append(
            "SITE VISIT: Conduct an unannounced site visit to the "
            "registered practice address to verify physical presence "
            "and operational capacity (42 CFR § 455.432)."
        )

    if "billing_concentration" in flag_names or "upcoding_pattern" in flag_names:
        actions.append(
            "CLAIMS AUDIT: Pull a statistically valid sample of claims "
            "for the dominant procedure code(s) and request supporting "
            "medical records to verify medical necessity and proper coding."
        )

    if "corporate_shell_risk" in flag_names or "address_cluster_risk" in flag_names:
        actions.append(
            "OWNERSHIP REVIEW: Request updated ownership and control "
            "disclosures (42 CFR § 455.104) for all NPIs associated "
            "with the same authorized official or physical address."
        )

    if "bust_out_pattern" in flag_names or "billing_ramp_rate" in flag_names:
        actions.append(
            "EXPEDITED REVIEW: The billing trajectory suggests a "
            "potential bust-out scheme. Prioritize this review to "
            "minimize continued overpayment exposure."
        )

    # Generic closing
    actions.append(
        "DOCUMENTATION: Preserve all claims data, correspondence, and "
        "investigative notes in the case management system for potential "
        "future referral to the U.S. Department of Justice under the "
        "False Claims Act (31 U.S.C. § 3729)."
    )

    content = "\n\n".join(f"{i+1}. {a}" for i, a in enumerate(actions))
    return {"title": "Recommended Actions", "content": content}


def _build_citations_section(provider: dict) -> dict:
    """Section (g): Consolidated regulatory citations."""
    signals = provider.get("signal_results") or []
    flags = [s for s in signals if s.get("flagged")]

    # Always include general citations
    all_citations = [
        "42 CFR Part 455 — Medicaid Program Integrity",
        "42 U.S.C. § 1320a-7b — Criminal Penalties for Acts Involving Federal Health Care Programs",
        "31 U.S.C. § 3729 — False Claims Act",
    ]

    # Add signal-specific citations
    seen = set(all_citations)
    for sig in flags:
        meta = _SIGNAL_META.get(sig.get("signal", ""), {})
        for cite in meta.get("citations", []):
            if cite not in seen:
                all_citations.append(cite)
                seen.add(cite)

    content = (
        "The following federal statutes and regulations are potentially "
        "applicable to the findings documented in this report:\n\n"
    )
    content += "\n".join(f"  - {c}" for c in all_citations)

    content += (
        "\n\nThis report is generated for program integrity purposes and "
        "does not constitute a legal determination of fraud. All findings "
        "are based on statistical analysis of claims data and should be "
        "verified through independent investigation before any adverse "
        "action is taken against the provider."
    )

    return {"title": "Applicable Regulatory Citations", "content": content}


def _build_review_status_section(review_item: Optional[dict]) -> Optional[dict]:
    """Optional section: Current case status from review queue."""
    if not review_item:
        return None

    status = review_item.get("status", "pending")
    assigned = review_item.get("assigned_to")
    notes = review_item.get("notes", "")
    added_at = review_item.get("added_at")
    updated_at = review_item.get("updated_at")

    content = (
        f"This provider is currently {_review_status_label(status)} "
        f"in the case management system."
    )

    if assigned:
        content += f" The case is assigned to {assigned}."

    if added_at:
        added_str = datetime.fromtimestamp(added_at).strftime("%B %d, %Y at %H:%M")
        content += f" The case was opened on {added_str}."

    if updated_at:
        updated_str = datetime.fromtimestamp(updated_at).strftime("%B %d, %Y at %H:%M")
        content += f" Last activity was recorded on {updated_str}."

    if notes and notes.strip():
        content += f"\n\nInvestigator notes: \"{notes.strip()}\""

    # Audit trail summary
    trail = review_item.get("audit_trail") or []
    if trail:
        content += (
            f"\n\nThe audit trail contains {len(trail)} recorded "
            f"action(s) since case creation."
        )

    return {"title": "Current Case Status", "content": content}


# ── Public API ───────────────────────────────────────────────────────────────

# In-memory narrative cache: npi -> {result, generated_at_ts}
_narrative_cache: dict[str, dict] = {}
_CACHE_TTL = 300  # 5 minutes


def generate_narrative(npi: str) -> dict:
    """
    Generate a complete investigation narrative for a provider.

    Returns:
        {
            narrative: str,          # Full prose narrative
            sections: list[dict],    # [{title, content}, ...]
            generated_at: str,       # ISO timestamp
            word_count: int,
        }

    Raises ValueError if NPI is not found in the prescan cache.
    """
    # Check cache
    now = time.time()
    cached = _narrative_cache.get(npi)
    if cached and (now - cached["generated_at_ts"]) < _CACHE_TTL:
        return cached["result"]

    # Find provider in prescan cache
    provider = None
    for p in get_prescanned():
        if p["npi"] == npi:
            provider = p
            break

    if not provider:
        raise ValueError(f"Provider {npi} not found in scan data")

    # Find review item (if any)
    review_item = None
    for item in get_review_queue():
        if item["npi"] == npi:
            review_item = item
            break

    # Build sections
    sections = [
        _build_subject_section(provider),
        _build_billing_section(provider),
        _build_risk_section(provider),
        _build_signal_findings_section(provider),
        _build_patterns_section(provider),
        _build_actions_section(provider),
        _build_citations_section(provider),
    ]

    # Insert review status section after risk assessment if available
    review_section = _build_review_status_section(review_item)
    if review_section:
        sections.insert(3, review_section)

    # Compose full narrative
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date_display = datetime.now().strftime("%B %d, %Y")

    header = (
        "MEDICAID PROGRAM INTEGRITY — INVESTIGATION NARRATIVE\n"
        f"Generated: {date_display}\n"
        f"Subject NPI: {npi}\n"
        "Classification: FOR OFFICIAL USE ONLY\n"
        "=" * 72
    )

    body_parts = []
    for i, section in enumerate(sections, 1):
        body_parts.append(
            f"\n{i}. {section['title'].upper()}\n"
            f"{'-' * 40}\n\n"
            f"{section['content']}"
        )

    narrative = header + "\n" + "\n".join(body_parts)
    word_count = len(narrative.split())

    result = {
        "narrative": narrative,
        "sections": sections,
        "generated_at": generated_at,
        "word_count": word_count,
    }

    # Cache result
    _narrative_cache[npi] = {"result": result, "generated_at_ts": now}

    return result
