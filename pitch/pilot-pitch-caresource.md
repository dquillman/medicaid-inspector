# Medicaid Inspector — 90-Day Pilot Proposal

> **Prepared for:** CareSource Special Investigations Unit
> **Prepared by:** Dave Quillman · Medicaid Inspector
> **Date:** 2026-05-28 · **Version:** 1.0 (template — tailor names and contract numbers before sending)
>
> Designed to be delivered as a 2-page PDF plus an appendix. Tailor `{{like-this}}` placeholders before sending.

---

## Glossary (first-mention expansions)

**MCO** — Managed Care Organization. **SIU** — Special Investigations Unit (private-payer fraud team). **PI** — Program Integrity (state-side detection unit). **MFCU** — Medicaid Fraud Control Unit (state Attorney General investigative/prosecutorial arm). **BAA** — Business Associate Agreement (HIPAA). **MSA** — Master Services Agreement. **MLR** — Medical Loss Ratio (capitation-based payer regulatory floor). **T-MSIS** — Transformed Medicaid Statistical Information System (CMS standardized claims feed). **PERM** — Payment Error Rate Measurement (CMS improper-payment program). **MMIS** — Medicaid Management Information System (state claims-processing system). **FWA** — Fraud, Waste, and Abuse.

---

## The problem we propose to address

A homebound CareSource beneficiary receives a knee brace they did not order and did not need, billed at $1,200. The "telemedicine consult" that "prescribed" it was a 90-second cold call from an out-of-state call center to a contracted physician who signed off on hundreds of identical orders that week. The brace was shipped by a DME supplier sharing a strip-mall address with eleven other supplier NPIs, all controlled by the same authorized official, all billing the same three MCOs. This is the OIG telefraud-DME pattern, run at scale on Medicaid books across multiple states.

CareSource's SIU is the team that has to find that pattern in eight figures of monthly claims, build the evidence package, refer to MFCU, and recover the dollars — while the next scheme is already running. The 2024 CMS improper-payment estimate for Medicaid was **$31.1B nationally**, a 5.09% improper-payment rate against **~$611B in federally-matched Medicaid outlays (PERM measurement base)** ([CMS PERM, 2024](https://www.cms.gov/data-research/monitoring-programs/improper-payment-measurement-programs/medicaid-and-chip-2024-improper-payment-data)). Separately, NHCAA estimates a conservative 3% of healthcare spending is lost to fraud; government and law-enforcement estimates run as high as 10% (>$300B annually) ([NHCAA 2024](https://www.nhcaa.org/tools-insights/about-health-care-fraud/the-challenge-of-health-care-fraud/)). Note: ~79% of the $31.1B PERM finding above is insufficient-documentation, not confirmed fraud — improper-payment recovery and fraud detection are related but distinct workstreams, both in MFI scope.

The friction we hear from MCO SIUs: **the existing detection toolchain is built for case management, not for upstream detection.** Legacy systems flood the queue with low-precision flags. Analysts learn to ignore them. The signals that *would* matter — address co-location, corporate-shell ownership, statistical outliers against specialty peers, diagnosis-procedure mismatch — either don't exist in the toolchain or require manual SQL by a data analyst who has 40 other priorities.

That's the gap we built Medicaid Inspector to close.

## What Medicaid Inspector is

> **Data provenance — disclosed upfront.** The 106,660-provider score base is built on public CMS provider datasets, which are Medicare-skewed (MUP-by-Provider and adjacent files). The six-signal logic is methodology-portable to Medicaid claims; the pilot is the first run against a Medicaid book, which is exactly why we propose calibration against your historic casework in weeks 1-4. We disclose this upfront because your data team will discover it in week one regardless.

A **production fraud-detection platform for Medicaid provider data**, currently scoring **106,660 providers** against six independent statistical and rule-based signals:

| Signal | Pattern detected | Pattern source (OIG / regulatory) |
|---|---|---|
| **Claims-per-beneficiary anomaly** | Providers >3σ above specialty peer mean in per-beneficiary claim volume | OIG ghost-billing & phantom-services indicators |
| **Beneficiary concentration** | Disproportionate share of revenue from a small set of beneficiaries | Industry phantom-billing pattern |
| **Upcoding pattern** | One high-reimbursement code dominating a provider's mix | OIG E/M upcoding work plan |
| **Address-cluster risk** | Many providers sharing a single address | OIG co-location flag |
| **Corporate-shell risk** | One authorized official controlling many NPIs | OIG shell-network indicator |
| **OIG exclusion cross-reference** | Match against the federal OIG LEIE | Statutory exclusion list |

OIG references describe the fraud *pattern*; the statistical operationalization, thresholds, peer-cohort construction, and min-N exclusion rules are MFI's own and are documented in the methods appendix (Appendix B).

The architecture is **stateless**: claims data is queried directly from your storage (DuckDB-over-Parquet, read-only); MFI never persists claims locally. **Composite weighted scoring** ranks providers; weights are documented in the methods appendix, signal-pair correlations are published, and the score is a **rank, not a calibrated probability** — top-k is to be worked top-down, NOT interpreted as "80/100 = 80% likely fraud." Configurable `alert_rules.json` lets SIU analysts retune thresholds without engineering involvement. HIPAA-aware audit logging captures every PHI access. (See attached security one-pager.)

## Why this survives review by your AG, the state MFCU, and a defense attorney

Every flag MFI surfaces carries, in the dossier:

- **(a)** the rule version that produced it (e.g., `address_cluster_risk@v2.3.1`)
- **(b)** underlying claim IDs that drove the score
- **(c)** the peer cohort used for comparison (taxonomy + state + panel-size band + year)
- **(d)** the threshold applied and the value the provider scored at
- **(e)** the date the rule was last edited and by whom (analyst-tunable rules carry change history)

When the case lands on an MFCU prosecutor's desk or a defense attorney's discovery request, the dossier itself is the chain-of-custody record. A redacted example dossier is in Appendix C.

## What we're proposing

A **fixed-scope, fixed-price, 90-day pilot** against your Ohio Medicaid book.

### Scope

- **Data:** A point-in-time extract of CareSource Ohio claims (2023-01 through 2025-12 recommended; minimum 24 months). **CareSource provisions a read-only GCS or Azure Blob container, populated with claims as Parquet files (schema spec attached). MFI's Cloud Run service queries the container via a scoped service-account credential CareSource issues and can revoke. Query results live only in MFI memory for the request duration; derived artifacts (queues, dossiers) live in MFI's GCP project under BAA. CareSource retains full audit visibility via storage access logs.** A one-page data-flow diagram is included as Appendix A.
- **Providers in scope:** ~8K–12K active Ohio-billing providers.
- **Signals run:** all six signals, plus calibration of thresholds against CareSource's historic SIU casework. **No prep work required from CareSource at kickoff. Your investigators' day-30 triage of MFI's ranked top-200 IS the calibration signal for day-60 tuning.** If a labeled outcomes file covering 18-24 months and 500+ closed dispositions is already accessible, we can additionally run retrospective validation (precision-at-k, recall-at-k); if not, we report ranked-list metrics with the limitation explicitly stated.
- **Outputs:** ranked review queue, per-provider evidence dossiers, exportable HTML investigation reports, weekly digest emails to the SIU lead.

### Schedule

| Phase | Day | Deliverable |
|---|---|---|
| Kickoff & data setup | 0 | Signed SOW, BAA executed, scoped service-account credential issued, first Parquet extract dropped into the read-only container |
| First ranked queue | 30 | Top-200 ranked providers across all six signals, with dossiers |
| Calibration pass | 60 | Refined queue using day-30 investigator dispositions; 3 deep-dive case write-ups |
| Outcomes report | 90 | Pilot results, precision/recall against CareSource's investigation outcomes, adopt/extend/end recommendation |

## How the queue reaches the investigator

Investigators should not have to leave their existing case-management system to use MFI. We support two delivery modes:

1. **Push into your case-management system** via API or scheduled file drop. We will adapt to Salesforce SIU Cloud, IBM i2, or homegrown systems — name yours in discovery.
2. **UI-light export-first mode** (CSV / FHIR / HTML dossiers) if your team prefers offline review.

If your investigators have to log into two systems to do their job, we have failed.

## Pricing

**$45,000 fixed price for the 90-day pilot.** No data-volume fees, no per-provider fees, no per-report fees. **Payment terms: 50% on signature, 50% on day 60.** Failure to deliver the day-30 and day-60 milestones reduces the fee proportionally; if at day 90 the SIU lead decides not to extend, we walk away.

### Production licensing — price-locked at pilot signature

- **Ohio production contract:** $8K–$12K/month base, **locked through day 180 if pilot success criteria met**.
- **Multi-state expansion:** −25% per-life price for state 2, −35% for states 3–7.
- **Three-year MSA option:** additional 15% discount.
- **Final pricing** set at day-75 of pilot, before the day-90 go/no-go decision.

You don't renegotiate from zero after we've shown you the product.

### Operational ROI — the math the SIU actually owns

**New evidence, not in any prior version of this pitch.** A field-shape bug in MFI's ownership-tracer (fixed this week, v3.7.3) had been silently zeroing shared-authorized-official matching across the entire provider base since launch. With the fix live, **97,926 of MFI's 106,660 scored providers (91.8%) now resolve to a named authorized official**, and the corrected corporate-shell signal (Appendix B, "Corporate-shell risk") surfaces **4,449 distinct clusters where two or more providers share a single authorized official** — the exact ownership-concentration pattern behind Operation Rubber Stamp and the shell-network cases cited below.

This is not a backtest or a sales projection. It is what MFI's own corporate-shell detector finds running against the current national base today, before a single Medicaid claim has been calibrated to CareSource's book. Some share of those 4,449 clusters will resolve to legitimate multi-clinic owner-operators or franchise groups under the peer-cohort and specialty-coherence checks described in Appendix B — that triage is precisely what the pilot's day-30/day-60 investigator review exists to do. But the more important number for a buyer evaluating vendor risk is this: **a shared-ownership pattern of this scale was invisible to MFI's own detector, silently, for the life of the product — until a code review caught it.** That is the argument for running the pilot now rather than waiting: if a purpose-built detector missed this at this scale, it is a near-certainty that legacy case-management tooling — which was never built to compute shared-authorized-official networks at all — is missing it too, in your book, right now.

A senior SIU investigator costs the MCO **~$150K loaded**. If they spend 60% of cycles triaging low-precision flags from legacy tooling, the implicit cost per *real* lead is high — and a number CareSource's own SIU lead can calculate exactly. MFI's pilot price implies a defined cost per investigation-worthy lead if our precision target holds (see "What success looks like" below) — break-even at a determinable number of leads.

Recoveries are downstream of investigation and prosecution; **we do not forecast them**. CareSource's own 2024 SIU recovery total is the right denominator for any ROI conversation; we propose the pilot success bar against your number, not an industry estimate. (We are also aware that MCO recoveries can net to the state via MLR true-up depending on contract structure — that's a conversation for your finance team, not a number we're going to bake into a slide.)

### What success looks like

**Two-tier success criteria, jointly signed in week 1.**

**LEADING (measured by day 30 and 60):**
- **(a) Precision-at-50** — % of MFI's top-50 providers that the SIU lead, in blinded review, rates investigation-worthy ≥7/10. **Target: ≥30%.**
- **(b) Net new leads** — count of top-50 NOT already in SIU's open or closed case file. **Target: ≥25.**

**LAGGING (day 90):**
- **Head-to-head precision bake-off** — MFI's top-50 reviewed alongside SIU's existing top-50 selected the same week, blind to source. Pilot succeeds if MFI's list achieves a confirmed-suspicious rate **at least equal to SIU's existing process** on closed dispositions.

These are auditable. They do not depend on an unprovable "would not have surfaced otherwise" counterfactual.

### What success unlocks

- A **production licensing conversation** at the price-locked rate above.
- An **expansion conversation** to CareSource's other state contracts at the published per-state discount schedule.
- A **case study** (jointly approved, scrubbed of all PHI and provider identifiers) that MFI can reference with other MCO SIUs.

## How we handle the certification gap

We do not yet hold SOC 2 Type II. We are addressing this three ways:

1. **MFI runs inside CareSource's existing audited environment** (customer-tenant deployment using a CareSource-controlled storage container and a scoped, revocable service-account credential), so MFI inherits CareSource's existing attestations for the data-at-rest path.
2. **MFI commits in the contract to begin SOC 2 Type II audit within 60 days of signed pilot**, with the first paid customer's pilot fee earmarked toward it.
3. **Interim controls:** HITRUST-aligned self-assessment via the **AHA Vendor Security Risk Assessment v6**; contractual security representations matching SOC 2 CC controls; customer right-to-audit clause; cybersecurity insurance certificate.

A pre-filled SIG Lite and AHA VSRA v6 questionnaire are attached so your Vendor Risk Management team can begin review in parallel with SIU discovery, not after.

## What MFI commits to

- **We commit to measure precision and recall transparently** and publish methodology in the pilot outcomes report.
- **We commit to surface investigation-ready candidates**; recoveries are the SIU's outcome to own.
- **We commit to a configurable rule engine** your analysts can tune without our engineering.
- **We commit to augment, not replace, investigators.** MFI ranks and surfaces; your investigators decide and act.
- **We commit not to lock you into our six signals.** Suppress, tune, or add — without vendor engineering involvement.

## What it takes to get to pilot kickoff

| # | Item | Owner on CareSource side | What MFI provides |
|---|---|---|---|
| 1 | 30-min discovery call to confirm top-3 detection gaps | SIU lead | Discovery agenda + signal-to-gap map |
| 2 | Executed BAA | CareSource Legal (2–4 wks typical) | Sample BAA template; we'll sign yours |
| 3 | InfoSec review | CareSource Vendor Risk Management (6–12 wks for vendor without SOC 2) | Pre-filled SIG Lite + AHA VSRA v6 + security one-pager |
| 4 | Designated SIU lead as pilot sponsor | CareSource SIU | Day-30, day-60, day-90 review templates |
| 5 | Data extract delivered to the read-only container | CareSource data governance + state contract review (**typically 6–12 weeks for first-time Medicaid extracts**) | Parquet schema spec; data-flow diagram; service-account credential request |

**Kickoff = data delivered, not contract signed.** We do not promise a 14-day data extract because no SIU lead can unilaterally produce a Medicaid claims extract that fast — it triggers HIPAA minimum-necessary review, state contract review, and potentially state Medicaid agency approval.

## Data quality, ecosystem, and the state

**Data quality (week-1 profiling).** Medicaid encounter and claims data quality varies by source — T-MSIS lag, managed-care encounter completeness, payment-amount field coverage. During kickoff week we profile the CareSource Ohio extract for completeness (missing NPIs, payment fields, date-range gaps, beneficiary-attribution accuracy) and document which of the six signals are reliably computable. **Signals that cannot be reliably computed will be flagged rather than silently degraded.**

**Working with the state ecosystem.** Outputs are designed to be referral-ready for MFCU (chain-of-custody preserved per dossier — see "Why this survives review"). MFI will work with CareSource compliance on whether the Ohio Medicaid contract requires state notification of a new subcontractor. **MFI does not compete with the state PI unit** — we are vendor to the MCO SIU, not to the state.

## Validation & affiliations

OIG Work Plan items each signal maps to are cited with publication dates in Appendix B. MFI is `{{member / pending-member}}` of HCCA, NHCAA, and AHIP. MFI is building an advisory board (target: retired state PI director + ex-MCO SIU lead, on retainer) — `{{names available on request once retainers signed}}`.

## How the loop closes

Investigator dispositions on flagged providers feed back into MFI weekly. MFI publishes a **monthly precision report per signal**. Quarterly, the SIU lead and MFI **jointly retire or retune signals that aren't earning their slot**. The feedback loop is part of the subscription, not the pilot — it is the reason this is a product, not a snapshot.

## Why CareSource

We are asking for a 30-minute call. Bring the toughest detection gap your current toolchain doesn't close. If we can show you a signal that maps to it, we'll scope a pilot together. If we can't, we'll tell you that, and you'll have spent 30 minutes.

---

## Appendix A: Data-flow diagram

*(One-page diagram attached as PDF. Shows: CareSource source systems → CareSource-controlled read-only Parquet container → scoped service-account credential → MFI Cloud Run query path → MFI-side derived artifacts under BAA → CareSource storage access logs as the audit record.)*

## Appendix B: Methods notes for all six signals

### Address-cluster risk

**Detection:** providers sharing a single physical address with ≥ 4 other unrelated providers (after deduplicating for group practices, hospitals, FQHCs, and known multi-tenant medical buildings).

**Pattern source:** OIG's *Special Fraud Alert: Telefraud Schemes* (2022) and multiple settled FCA cases (notably Operation Rubber Stamp, DOJ/HHS-OIG October 2020, $1.5B+ in fraudulent billings identified — primarily telemedicine-kickback and DME, with shared-address shell-billing patterns).

**MFI implementation:** address normalization (USPS-grade) → distance-clustering → suppression of known multi-tenant buildings (hospital MOBs, university health systems) → rank by cluster size × billing concentration.

**Confidence calibration:** For each provider in a cluster of size ≥5, compare that provider's Medicaid billing to the median of all active billers in the same taxonomy code, same state, same year, with min-N panel size of **30 beneficiaries**. Flag the cluster if **≥50%** of providers in it exceed 1.5× the comparator median. Tunable per SIU.

**Known confounds:** large multi-tenant medical office buildings (suppressed via building registry); group practices with many sub-NPIs under one address (handled via TIN-grouping); rural address sharing where the closest commercial address serves a wide catchment (handled via cluster-size-vs-county-density check).

### Corporate-shell risk

**Detection:** one authorized official (NPPES record) listed as the controlling person on ≥ 3 distinct NPIs across distinct legal entities, weighted by combined billing.

**Pattern source:** OIG's corporate-shell taxonomy explicitly names this pattern. Recent enforcement examples: **U.S. v. Sekhar Rao (5th Cir. 2024 — toxicology/DNA-testing shell entity ADAR Group LLC, billed to TRICARE).** Additional verified shell-network cases drawn from DOJ's annual Health Care Fraud and Abuse Control Program report.

**MFI implementation:** parse NPPES authorized-official field → fuzzy-match on name + DOB + email → graph-network construction → rank by network size × billing concentration × specialty diversity.

**Cohort & min-N:** networks of ≥3 NPIs with combined annual Medicaid billing ≥ $250K.

**Known confounds:** legitimate multi-clinic owner-operators (handled via specialty-coherence check); common-name false matches (handled via DOB/email/license-state corroboration); franchise medical groups (whitelist).

### Upcoding pattern

**Detection:** providers whose E/M code distribution skews ≥ 2σ toward the highest reimbursement codes (e.g., 99215 / 99205) vs. specialty peers.

**Pattern source:** OIG E/M upcoding work plan; CMS Targeted Probe & Educate program; multiple six-figure False Claims Act settlements every quarter.

**MFI implementation:** E/M code distribution per provider → specialty peer cohort (same taxonomy, same state, same panel-size band) → z-score the high-code share → flag if z > 2.

**Cohort & min-N:** cohort minimum 30 providers; provider minimum 200 E/M claims in the window.

**Time-window stability:** signal evaluated on rolling 12-month windows; alerts only fire if the z-score is sustained across 2 consecutive 6-month windows.

**Known confounds:** legitimate complex-case specialty patterns (oncology, complex internal medicine — handled via specialty-specific cohorts); panel-size effects on small-N providers (handled via min-N threshold); coding-software default behavior at certain group practices (handled via TIN-clustering check).

### Claims-per-beneficiary anomaly

**Detection:** providers >3σ above specialty peer mean in per-beneficiary claim volume.

**Pattern source:** OIG ghost-billing and phantom-services indicators.

**Cohort & min-N:** same taxonomy / state / year cohort; provider min 50 unique beneficiaries.

**Known confounds:** chronic-care management providers (cohort'd separately); high-acuity specialty (oncology, dialysis); short window of high billing from a single hospitalized patient (handled via beneficiary-day-count normalization).

### Beneficiary concentration

**Detection:** Top-N beneficiaries account for disproportionate share of provider's claims revenue (Herfindahl-style concentration index above cohort 95th percentile).

**Pattern source:** Industry phantom-billing pattern; OIG referenced in multiple work-plan items on per-patient billing extremes.

**Cohort & min-N:** specialty / state / panel-size band; provider min 100 beneficiaries.

**Known confounds:** legitimate boutique / concierge practices (rare in Medicaid but flagged for human review); home-health where one beneficiary may generate many claim lines (handled via claim-line-vs-claim-event normalization).

### OIG exclusion cross-reference

**Detection:** match between provider NPI / name / DOB and federal OIG LEIE exclusion list.

**Pattern source:** Statutory — 42 USC 1320a-7. Excluded providers cannot bill federal healthcare programs.

**MFI implementation:** weekly LEIE pull; fuzzy match on NPI (exact) + name (Jaro-Winkler ≥ 0.92) + DOB (exact when available); flag on match.

**Known confounds:** common-name false matches (handled via DOB corroboration); reinstated providers (LEIE flag clears within 7 days of reinstatement notice).

## Appendix C: Redacted example dossier

*(One-page redacted dossier attached. Shows: provider identifier `PROVIDER-001`, NPI `1XXXXXXXXX`, signal flags fired, rule versions, peer cohort, threshold values, claim IDs driving the score, rule-change history, last reviewed-by analyst.)*

---

**Contact**
Dave Quillman · dquillman2112@gmail.com · {{phone}}
Medicaid Inspector · medicaid-inspector.web.app
