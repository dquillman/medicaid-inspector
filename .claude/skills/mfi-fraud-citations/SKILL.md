---
name: mfi-fraud-citations
description: Authoritative reference mapping every fraud signal in the Medicaid Inspector app to its supporting CFR / USC citation and the OIG context that justifies it. Use this skill whenever you need to cite the law behind a flagged signal — for example when drafting a case narrative, answering "what statute covers upcoding?", explaining why a flag matters, or grounding a recommendation to refer a provider. Trigger on phrases like "cite the law for X", "what regulation covers X", "is there a statute for X", "what's the citation for the X signal", or any free-text question that asks for the legal basis behind a fraud flag. Synced from `backend/services/narrative_generator.py::_SIGNAL_META` — if the citations in the code change, regenerate this file.
---

# Medicaid Fraud Signal → Statute Map

This skill is the canonical mapping of the 17 fraud-detection signals in the Medicaid Inspector app to their legal authority. The Python codebase (`backend/services/narrative_generator.py`) embeds the same data inside the case-narrative templates; this Skill exposes it for Claude to cite in conversation without needing the source file open.

Cite EXACTLY as written below. Do not paraphrase statute numbers. If a question covers a pattern not listed, say so and offer to look it up — do not fabricate a citation.

## The 17 signals

### 1. Billing Concentration (`billing_concentration`)
**What it detects:** A disproportionate share of total Medicaid reimbursement comes from a single procedure code. Hallmark of billing-mill operations.
- 42 CFR § 455.23 — provider screening and enrollment
- 42 U.S.C. § 1320a-7b(a) — False Claims (billing for services not rendered)
- OIG Medicaid Fraud Control Units Annual Report FY2024

### 2. Revenue Per Beneficiary Outlier (`revenue_per_bene_outlier`)
**What it detects:** Per-beneficiary revenue is statistically anomalous vs. peers billing the same HCPCS codes. Indicator of upcoding, unbundling, or phantom services.
- 42 CFR § 455.14 — State plan requirement for fraud detection
- 42 U.S.C. § 1320a-7a — Civil monetary penalties for false claims
- OIG Work Plan — Statistical Anomaly Detection Guidance

### 3. Claims Per Beneficiary Anomaly (`claims_per_bene_anomaly`)
**What it detects:** Claims-per-beneficiary volume exceeds statistical norms. Suggests service duplication, phantom billing, or medically unnecessary services.
- 42 CFR § 456.3 — Utilization control (State plan requirements)
- 42 U.S.C. § 1320a-7b(b) — Anti-kickback provisions

### 4. Billing Ramp Rate (`billing_ramp_rate`)
**What it detects:** Explosive billing increase over a short period, especially coupled with a newly enumerated NPI. CMS FPS primary screening criterion for bust-out schemes.
- 42 CFR § 455.23 — Temporary moratoria on enrollment of new providers
- CMS Fraud Prevention System (FPS) methodology — ramp-rate screening

### 5. Bust-Out Pattern (`bust_out_pattern`)
**What it detects:** Peak-then-exit trajectory in billing data. Documented in OIG enforcement: providers escalate billing to extract max reimbursement before abandoning the practice.
- 42 U.S.C. § 1320a-7(a) — Mandatory exclusion from Federal health care programs
- OIG Semiannual Report to Congress — bust-out scheme case studies

### 6. Ghost Billing / Beneficiary Suppression (`ghost_billing`)
**What it detects:** Beneficiary count at/near the CMS 12-beneficiary suppression floor while claim volume or revenue is disproportionately high. Suggests manipulation of beneficiary-level data or phantom beneficiaries.
- 42 CFR § 455.18 — Provider disclosure requirements
- 42 U.S.C. § 1320a-7b(a)(1) — False statements (material misrepresentation)

### 7. Beneficiary Concentration (`bene_concentration`)
**What it detects:** Extremely high claims-per-beneficiary ratio — small number of beneficiaries billed at unusually intensive rates. Indicates phantom billing, unnecessary services, or patient-captivity schemes.
- 42 CFR § 456.3 — Utilization control (State plan requirements)
- 42 U.S.C. § 1320a-7a — Civil monetary penalties

### 8. Upcoding Pattern (`upcoding_pattern`)
**What it detects:** Billing concentrated on the highest-reimbursement procedure codes relative to peers. One of the most common forms of Medicaid fraud identified by OIG.
- 31 U.S.C. § 3729 — False Claims Act (treble damages)
- 42 U.S.C. § 1320a-7a(a)(1) — Civil monetary penalties for upcoding
- OIG Work Plan — Upcoding Detection Methodology

### 9. Address Cluster Risk (`address_cluster_risk`)
**What it detects:** Multiple billing providers registered at the same physical address. High NPI concentration at one address is a known shell-company indicator cited in OIG prosecutions.
- 42 CFR § 455.104 — Disclosure of ownership and control
- 42 CFR § 455.106 — Disclosure of business transactions

### 10. OIG Exclusion List Match (`oig_excluded`)
**What it detects:** Provider appears on the OIG List of Excluded Individuals/Entities (LEIE). Billing by an excluded provider is a per-item violation.
- 42 U.S.C. § 1320a-7 — Exclusion of certain individuals and entities
- 42 CFR § 1001.1901 — Scope and effect of exclusion
- 42 U.S.C. § 1320a-7a — Civil monetary penalties (up to $100,000 per item)

### 11. Specialty Mismatch (`specialty_mismatch`)
**What it detects:** Billing patterns don't align with enrolled NPPES specialty. May indicate identity theft, credentialing fraud, or services rendered by unlicensed personnel.
- 42 CFR § 455.410 — Provider enrollment screening levels
- 42 U.S.C. § 1320a-7b(a)(6) — False statements regarding provider status

### 12. Corporate Shell Risk (`corporate_shell_risk`)
**What it detects:** A single authorized official controls multiple billing NPIs. Documented feature of corporate-shell fraud schemes.
- 42 CFR § 455.104 — Disclosure of ownership and control
- 42 CFR § 455.106 — Disclosure of business transactions
- 42 U.S.C. § 1320a-7b(b) — Anti-kickback statute (corporate arrangements)

### 13. Deactivated NPI Billing (`dead_npi_billing`)
**What it detects:** NPI deactivated in NPPES but still appears on Medicaid claims. Indicates identity theft or use of abandoned credentials.
- 45 CFR § 162.408 — NPI deactivation procedures
- 42 U.S.C. § 1320a-7b(a) — False statements (use of deactivated identifier)

### 14. New Provider Billing Explosion (`new_provider_explosion`)
**What it detects:** Newly enumerated NPI generating billing disproportionate to operational tenure. OIG documents that fraudulent providers exploit the enrollment window before detection triggers.
- 42 CFR § 455.23 — Temporary moratoria on enrollment of new providers
- CMS Fraud Prevention System — new-provider screening protocol

### 15. Geographic Impossibility (`geographic_impossibility`)
**What it detects:** NPPES practice location in a different state from where Medicaid claims are submitted. Telemedicine can explain some — complete mismatch warrants investigation.
- 42 CFR § 455.410 — Provider enrollment (site visits)
- 42 U.S.C. § 1320a-7b(a)(1) — False statements (fictitious practice)

### 16. Total Spend Outlier (`total_spend_outlier`)
**What it detects:** Total Medicaid payments statistically anomalous vs. the broader population. Extreme total spend is the single strongest fraud predictor in OIG's statistical methodology.
- 42 CFR § 455.14 — State plan requirement for fraud detection
- OIG Work Plan — Total Spend Outlier Detection

### 17. Billing Consistency Anomaly (`billing_consistency`)
**What it detects:** Monthly billing amounts unnaturally uniform. Legitimate practices vary month-to-month; flat-line billing indicates automated/template-based claim submission.
- 42 CFR § 455.23 — Provider screening requirements
- CMS FPS — automated claims detection algorithm

## Cross-cutting authorities (always-applicable)

These statutes apply to virtually any Medicaid fraud referral. Cite them in the "general legal framework" section of a narrative even when no specific signal points to them:

- **42 CFR Part 455** — Medicaid Program Integrity
- **42 U.S.C. § 1320a-7b** — Criminal Penalties for Acts Involving Federal Health Care Programs
- **31 U.S.C. §§ 3729-3733** — False Claims Act (treble damages, qui tam provisions)
- **18 U.S.C. § 1347** — Federal Health Care Fraud (criminal)
- **18 U.S.C. § 1035** — False Statements Relating to Health Care Matters

## How to use this skill

When a user asks for the citation behind a signal:

1. Identify the signal by its short name (`billing_concentration`, `oig_excluded`, etc.) or human label.
2. Cite the entries verbatim from the section above. Include both the CFR/USC numbers AND the short description in parentheses.
3. If multiple signals fired, group the citations under each signal heading — do not flatten into a single list (the heading matters for legal clarity).
4. If asked about a pattern not in this list (e.g., kickback, Stark, prescription fraud, Anti-Kickback Statute specifics), defer:
   - Stark / self-referral → 42 U.S.C. § 1395nn
   - Anti-Kickback Statute (criminal) → 42 U.S.C. § 1320a-7b(b)
   - Civil False Claims Act → 31 U.S.C. § 3729
   - Federal health care fraud (criminal) → 18 U.S.C. § 1347
   - Identity theft (aggravated) → 18 U.S.C. § 1028A

## Anti-patterns — do not do these

- **Do not** invent a CFR or USC number. If you don't have it in this file, say so.
- **Do not** strip the parenthetical description — investigators rely on the short description to know which subsection actually fits the facts.
- **Do not** recommend MFCU referral based solely on this Skill — that decision belongs to the `mfi-investigate-provider` agent (which weighs the score, signal count, and exclusion status together).
- **Do not** modify statute numbers based on training-data updates. The CFR/USC numbers here are static legal references; year-version differences may exist but the section numbers cited are the authoritative ones used by OIG.

## When to regenerate this file

Trigger a refresh of this skill whenever:
- A new signal is added via the `signal-author` agent — it adds a new `_SIGNAL_META` entry that must be mirrored here.
- An existing signal's citations are amended in `backend/services/narrative_generator.py`.
- The OIG publishes a new Work Plan that supersedes one of the cross-cutting authorities.

To regenerate: read `_SIGNAL_META` from `backend/services/narrative_generator.py` and rewrite each `### N. <Label>` block accordingly. Keep the order in sync with the dict.
