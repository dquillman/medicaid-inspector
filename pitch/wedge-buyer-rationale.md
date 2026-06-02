# Wedge Buyer Decision — MFI

> **🛑 Campaign status: PAUSED — RESERVE artifact.** Sales campaign deferred indefinitely while MFI is in solo-founder dogfood mode (Dave-as-tipster submitting to HHS-OIG Hotline + state MFCUs). This document is the ready-to-fire playbook for when a sales-readiness trigger fires — see `README.md` for the four triggers (T1–T4). Until then: no outbound, no pitch PDFs, no security one-pagers sent.
>
> **Decision (when campaign reactivates):** **CareSource SIU** (Dayton, OH) is the primary wedge buyer, with **AmeriHealth Caritas SIU** and **Molina Healthcare SIU** run in parallel from week 1.
>
> **Last updated:** 2026-05-29 · **Owner:** Dave · **Status:** RESERVE — gated on T1–T4 trigger per `README.md` · **Revisit:** when a trigger fires, OR if the dogfood phase generates new strategic intel that changes the segment thesis

---

## TL;DR

The wedge segment, **when this campaign eventually reactivates**, is **MCO Special Investigation Units, not state Program Integrity units.** Within MCO SIUs, the wedge target is a **mid-sized Medicaid-dominant MCO that's small enough to move and big enough to have a real SIU budget.** CareSource fits: ~2M+ members (Medicaid-dominant book with Medicare Advantage / D-SNP / ACA Marketplace lines), ~$13B revenue (2024), regional rather than national, single-state HQ (Dayton OH), nonprofit founded 1989. Win one CareSource state contract and you have a credible reference for AmeriHealth Caritas, Molina, and eventually Centene. Lose six months chasing a state PI unit and you have nothing.

**Current stance — read this before the strategy below:** The MCO SIU sales campaign is **PAUSED**. Dave is using MFI himself to submit tips to HHS-OIG Hotline and state MFCUs. The campaign reactivates only when one of T1–T4 fires per `README.md`. The strategy below is **what to do then**, not what to do now.

**Validation status:** The wedge thesis is built on secondary research plus one informal conversation with an investigator friend who originated the product idea. The friend session (see `What's active right now` in `README.md`) will collapse most of what the original "Phase 0 — 5-10 SIU discovery calls" section below was supposed to produce. Treat the Phase 0 section as superseded; the friend session + the dogfood tip-submission feedback loop are now the validation channel.

---

## What we've validated

> **STATUS: EMPTY.** No SIU or ex-SIU conversations have been logged yet. Until this table has 5+ entries, this document is DRAFT and pilot-pitch-caresource.md does not go out.

| # | Date | Role (anonymized) | Source channel | Top pain point heard | Tooling in use | Quote (anonymized) |
|---|------|-------------------|----------------|---------------------|----------------|---------------------|
| _(none yet)_ | | | | | | |

**Top-3 pain points heard (to populate after calls):**
1. _TBD_
2. _TBD_
3. _TBD_

---

## Glossary (first-mention expansions)

- **MCO** — Managed Care Organization (the health plan that holds a Medicaid state contract and bears actuarial risk)
- **SIU** — Special Investigations Unit (the MCO's internal fraud, waste, and abuse team)
- **PI** — Program Integrity (the state Medicaid agency's parallel function)
- **MFCU** — Medicaid Fraud Control Unit (state Attorney General's investigative/prosecutorial arm; federally certified)
- **BAA** — Business Associate Agreement (HIPAA contract required for any vendor touching PHI)
- **MSA** — Master Services Agreement (umbrella vendor contract under which SOWs are issued)
- **SOW** — Statement of Work (specific engagement under an MSA)
- **MLR** — Medical Loss Ratio (regulated minimum % of premium spent on care; SIU recoveries affect this calculation)
- **T-MSIS** — Transformed Medicaid Statistical Information System (CMS's national Medicaid claims dataset)
- **PERM** — Payment Error Rate Measurement (CMS program measuring improper Medicaid payments per state)
- **MMIS** — Medicaid Management Information System (the claims-processing system each state operates)
- **PHI** — Protected Health Information (HIPAA-defined patient data)
- **SOC 2** — Service Organization Control 2 (audited control framework; Type II covers operating effectiveness over time)
- **HITRUST** — Health Information Trust Alliance certification (healthcare-specific control framework)
- **SIG Lite / AHA VSRA** — Standardized vendor security questionnaires used by payers

---

## Phase 0 — SUPERSEDED by the dogfood phase

> **This section is preserved for historical reference. It described a "5-10 unpaid SIU discovery calls" gate that has been replaced by two cheaper, higher-signal channels** (per the 2026-05-29 strategic pivot).

**What replaced it:**

1. **The investigator-friend session** — Dave already has one qualified MCO-SIU-adjacent contact (the originator of the product idea). One 90-minute paid session with him replaces 5+ cold discovery calls. See `README.md` § "What IS active right now" item #2.
2. **The dogfood tip-submission loop** — every tip Dave files to HHS-OIG Hotline or a state MFCU surfaces real friction in the product (export gaps, methodology gaps, dossier gaps) more reliably than any cold call would. The submission workflow IS the validation harness.

**If the campaign reactivates and the friend channel is exhausted before pipeline coverage is sufficient,** fall back to the original Phase 0 playbook below as a secondary discovery channel:

- NHCAA (National Health Care Anti-Fraud Association) Annual Training Conference attendee list
- HCCA (Healthcare Compliance Association) chapter meetings in OH, GA, IN
- LinkedIn search: "Special Investigations" + "Medicaid" + tenure exited 2024–2026 (ex-SIU contacts speak more freely)
- Town Hall Ventures portfolio CEO intros (per the Slavitt connection)
- Warm referrals from anyone currently consulting to MCO compliance teams

**Pitch for those calls** (same as before): *"I'm not selling anything. I'm building a Medicaid fraud detection tool and I want 30 minutes to understand what your queue actually looks like, what tooling you've abandoned, and what would make a vendor pitch worth reading. I'll send you whatever I learn from the other calls."*

**Capture per call:** current toolchain, queue volume, top 3 pain points, last vendor pilot they ran (and why it ended), how their recoveries are measured, who signs a $45K SOW.

---

## Why MCO SIU over State PI Unit

Both are real fraud-fighting roles. They are not the same buyer.

| Dimension | State PI Unit | MCO SIU | Why this matters for MFI |
|---|---|---|---|
| **Sales cycle** | 12–24 months (RFP-driven, statutory) | 4–9 months (contract amendment or sole-source for SIU tooling under threshold) | A solo founder can survive 2 MCO cycles; can survive ~1 state cycle before cash runs out |
| **Budget authority** | Director must defend a line item against the legislature each biennium | SIU lead has discretionary budget within the MCO's medical-loss-ratio plan | Authority to write a check ≠ authority to influence one |
| **Procurement vehicle** | RFP / GSA-style cooperative / state IT consortium | Vendor MSA + SOW, often with the parent MCO's existing procurement office | RFP responses cost ~$30K and ~6 weeks each. MSA negotiation for a first-time PHI-handling vendor: **8–16 weeks once vendor risk, privacy, infosec, and legal review are sequenced** |
| **Measured on** | Compliance reports to CMS; reduction in improper-payment rate (slow signal) | Recoveries net of recovery costs; ratio of dollars recovered per investigator-hour (fast signal) | An SIU lead can show ROI in a quarter. A PI director can show it in a year. Quarter > year |
| **Procurement risk tolerance** | Low — political cost of a vendor failure | Moderate — vendor fails, MCO swaps it out quietly | Pilots that "didn't quite hit" don't kill the buyer's career at an MCO |
| **Reference value** | One state win unlocks: maybe 1–2 sibling states over 18 months | One MCO-line win unlocks: improved win odds in that MCO's other state contracts, but **9–18 months per follow-on state** with separate state-side data agreement and security review. Cross-MCO references (CareSource → AmeriHealth) require a deliberate co-branded artifact (e.g., joint NHCAA conference talk) — MCO competitors do not share vendor experiences freely | MCO wins compound, but not automatically and not geometrically — each new state is a real sale |
| **HIPAA/security posture demand** | Very high — state CISO, AG review, possible SoS attestations | High — MCO security review, BAA, increasingly SOC 2 Type II or HITRUST asks | MCO security review is typically more contained in scope (no state AG sign-off, no SoS attestation), but increasingly demands SOC 2 Type II or HITRUST for any vendor touching PHI at scale. Expect **6–12 weeks for a vendor without SOC 2** |
| **Number of buyers in the segment** | ~56 (50 states + DC + 5 territories) | ~150+ Medicaid MCO state contracts across the country (one MCO can hold 6+) | More shots, smaller targets |

**The math:** A solo founder with 12 months of runway can run ~3 serious MCO sales motions in parallel, or ~1 serious state RFP. Three at-bats beats one at-bat unless the one at-bat has a >3x higher hit rate — which it doesn't. State PI is the harder sale.

**The non-obvious reason:** State PI units have *already* bought from incumbents (LexisNexis, Optum, Conduent/Gainwell, SAS Fraud Framework) under multi-year contracts. Displacing those vendors mid-contract is structurally impossible. MCO SIUs are more likely to layer a specialized detection tool on top of their existing investigation case-management system without needing to rip out an incumbent.

---

## Why CareSource (specifically)

Among Medicaid-focused MCOs, the wedge target needs four properties:

1. **Medicaid is the majority of their book** (otherwise the SIU is staffed for commercial-side fraud, not Medicaid-specific patterns)
2. **Mid-sized** — small enough that the SIU lead can take a meeting with a solo vendor; big enough that the SIU has real budget
3. **Multi-state contract footprint** — so one win replicates across states
4. **Regional HQ, not Fortune 50 conglomerate** — Centene and UnitedHealth have procurement offices designed to break the spirit of small vendors

### ICP scorecard — MCO attributes

| Attribute | Target (green) | Yellow | Red | CareSource | AmeriHealth Caritas | Molina |
|---|---|---|---|---|---|---|
| Medicaid mix % of book | >60% | 30–60% | <30% | 🟢 dominant | 🟢 dominant | 🟢 dominant |
| Total members | 1–6M | 6–15M | >15M (Fortune 25 procurement) | 🟢 ~2M+ | 🟢 ~3M | 🟡 ~5.3M |
| # active state Medicaid contracts | 5–12 | 2–4 or 13–20 | 1 or >20 | 🟢 7+ (OH, GA, IN, KY, WV, NC, AR, MI via HAP JV, MS via TrueCare) | 🟡 12+ | 🟡 ~19 |
| Procurement vehicle | MSA amendment under threshold | MSA + corporate-procurement review | Public RFP only | 🟢 amendable | 🟡 layered via Independence parent | 🟡 public-co scrutiny |
| Parent / corporate structure | Nonprofit or single-purpose | Mutual/semi-mutual | Fortune 50 / conglomerate / public co. | 🟢 nonprofit | 🟢 Independence-affiliated | 🟡 NYSE-listed |
| HQ posture | Regional, Midwest/non-coastal | Coastal mid-market | Manhattan/Bay Area HQ | 🟢 Dayton OH | 🟢 Philadelphia PA | 🟡 Long Beach CA |
| **MCO score** | | | | **🟢 6 green** | **🟢 3 green / 3 yellow** | **🟡 2 green / 4 yellow** |

### ICP scorecard — Persona attributes

| Attribute | Target (green) | Yellow | Red |
|---|---|---|---|
| SIU title seniority | Director or VP of SIU / Program Integrity | Senior Manager | Analyst, or C-suite |
| Tenure in current role | 6–24 months (still proving themselves, willing to try new tools) | 24–60 months | <6 months (no political capital) or >60 months (set in toolchain) |
| Prior tooling churn | Has killed at least one vendor in last 24 months | Has done one pilot, undecided | Long-term incumbent loyalist |
| Measurement basis | Recoveries-quota or dollars-per-investigator-hour | Mixed compliance + recoveries | Compliance-only |
| Authority for $45K SOW | Can sign within MSA without board | Needs ops VP co-sign | Needs board / quarterly review |
| **Persona score** | | | (score 1–5 per axis post-discovery call) |

**Use:** disqualify on the discovery call, not after a 6-week security review. A Yellow MCO with a Green persona may still be worth pursuing; a Green MCO with a Red persona is not.

### Why CareSource wins this matrix

- **Medicaid-dominant book.** Government programs are the majority of their business (Medicaid plus Medicare Advantage / D-SNP / MyCare). The SIU is calibrated to Medicaid patterns, not commercial PPO fraud. (Note: CareSource also has ACA Marketplace; they announced exiting KY/MI/NC marketplaces Jan 1, 2026.)
- **Mission-driven culture.** CareSource was founded as a nonprofit in 1989 and retains the operational tone. SIU leads care about preventing harm to beneficiaries, not just hitting recovery quotas — which is exactly how MFI should be positioned.
- **Regional, not coastal-elite.** A solo founder in the Midwest (you, Dave) calling Dayton lands better than calling Manhattan. The fit is cultural, not just commercial.
- **Multi-state footprint.** Win their Ohio SIU and a positive internal reference improves win odds in CareSource's other state contracts (GA, IN, KY, WV, NC, AR, MI via HAP CareSource JV, MS via TrueCare). Expect 9–18 months per follow-on — each is a separate sale with its own state-side data agreement and state Medicaid agency review.
- **Procurement is amendable.** Their existing vendor MSAs allow SOW amendments under thresholds without re-RFP — meaning a $40K–$75K pilot can plausibly be authorized in 30–45 days *after* the security review completes (which itself is the longer pole).

### Why not the backups as primary

- **AmeriHealth Caritas** has 12+ state contracts (better replication math) but a more layered procurement office driven by Independence Health Group corporate. Slower to first dollar.
- **Molina** is publicly traded; SIU spend is scrutinized at the quarterly-earnings level. Pilots get blessed but slower; expect 9-month cycle vs. CareSource's 6–9.

---

## Buyer map — stakeholder table

Single-threading the SIU lead is how this deal stalls in week 8–12 with no visibility into who actually signs. Multi-thread from week 1.

| Role | Title (typical) | Cares about | Artifact MFI owes them | Question they will ask |
|---|---|---|---|---|
| **Champion** | SIU Director / Director of Program Integrity | Queue precision, analyst hours saved, defensible case write-ups | Pilot proposal + signal methodology + ranked-queue sample | "How is this different from the rules engine we already have?" |
| **Economic buyer** | VP Medical Economics or CFO of the Health Plan / Government Programs | Net recoveries vs. tooling spend, MLR impact, contract length | ROI model with conservative assumptions; reference customer (post-pilot) | "What's the all-in cost over 24 months and what's the floor on recoveries?" |
| **Security / IT** | CISO or Vendor Risk Lead | BAA, SOC 2 Type II, data residency, deletion attestation, audit log retention | Security one-pager, pre-filled SIG Lite or AHA VSRA v6, BAA template, architecture diagram | "Where does PHI live, who has access, and how do you prove deletion?" |
| **Procurement** | MSA office / Vendor Management | Contract length, termination-for-convenience clause, indemnification cap, insurance limits | Redlined MSA + SOW with caps clearly stated; certificates of insurance | "What's your COI limit and your liability cap?" |

---

## The path

**Phase 0 — Validate (pre-launch).** See section above. Gate on completion.

**Phase 1 — Land the meeting, run all three MCOs in parallel (weeks 0–4 post-Phase 0).**
- Identify the SIU lead at CareSource, AmeriHealth Caritas, and Molina by name (LinkedIn + AHIP / NHCAA attendee lists).
- Warm intro preferred: HCCA chapter members in OH/PA/CA; NHCAA Annual Training Conference; Town Hall Ventures portfolio CEOs.
- Cold-email fallback: subject line "Six-signal Medicaid provider scoring — 30-min look?", body under 120 words, **zero attachments**, one specific question, one calendar link. Hold the security one-pager until after the discovery call, when InfoSec is named as the next gate.
- **In parallel with discovery outreach:** send `security-compliance-onepager.md` + a pre-filled SIG Lite or AHA VSRA v6 to the Vendor Risk contact at each MCO so the security review clock starts now, not after Phase 3.

**Phase 2 — Discovery call (weeks 4–6).**
- Goal: confirm SIU's top 3 detection gaps and disqualify fast if MFI doesn't map.
- Use the 10-question qualifying matrix below. Score 1–5 per axis post-call.
- Hard rule: do not pitch. Listen.

### 10-question discovery qualifying matrix (BANT-adapted for SIU)

| # | Question | Axis | Disqualifier if… |
|---|---|---|---|
| 1 | What's in your current detection toolchain, and what budget line does it sit under? | Budget | No discretionary line; everything routed through corporate IT |
| 2 | Who signs a $45K SOW for an SIU tool — you, the VP, or the board? | Authority | Board only, with annual review cycle |
| 3 | What are your top three detection gaps right now? | Need | Gaps don't map to any of MFI's 18 signals |
| 4 | When did you last experience a material fraud-loss event, and what did you wish you'd had? | Need | "We're fine, nothing recent" — no felt pain |
| 5 | What vendor pilots have you run in the last 24 months, and how did they end? | Timing / risk | Loyal to incumbent, no churn history |
| 6 | What does a successful pilot look like at day 90 — in numbers? | Need / metrics | Can't articulate; success is undefined |
| 7 | Walk me through how a typical case moves from queue to recovery. | Process fit | MFI doesn't fit the actual case workflow |
| 8 | Who owns BAA execution and how long does it typically take here? | Timing | >16 weeks BAA cycle or no clear owner |
| 9 | What does your vendor security review look like — SIG Lite, AHA VSRA, custom? Is SOC 2 Type II a hard gate? | Security | SOC 2 Type II is a hard gate AND we don't have it AND they won't accept compensating controls |
| 10 | If we ran a 90-day pilot on Ohio data starting next month, what would have to be true for it to convert to production? | Close plan | No clear path; "we'd have to see" |

**Five explicit disqualifiers:**
1. No discretionary budget — purchase requires net-new line item through next year's budget cycle
2. SOC 2 Type II is a hard gate with zero compensating-control flexibility (until MFI has SOC 2)
3. Champion has <6 months tenure (no political capital to push) or >60 months (too entrenched in incumbent)
4. Already mid-contract with a direct competitor (Codoxo, Cotiviti, Optum HFS) with >12 months remaining
5. No felt pain — "we're fine" — no recent fraud-loss event and no measurement basis tied to recoveries

**Phase 3 — Tailored pilot proposal (weeks 6–8).**
- See `pilot-pitch-caresource.md` for the template.
- Scope: 90 days, single state contract (Ohio), 8K–12K providers, fixed-price.

**Phase 4 — Security review close-out (weeks 4–16 — runs in parallel from Phase 1).**
- This is the longest pole and the most likely deal-killer. Budget **8–12 weeks** of back-and-forth with MCO InfoSec on data-handling, deletion, audit logging — and **6–12 weeks total** for a vendor without SOC 2 Type II.
- Materials already in flight from Phase 1: `security-compliance-onepager.md`, pre-filled SIG Lite or AHA VSRA v6, BAA template, architecture diagram.

**Phase 5 — Pilot kickoff (weeks 16–24).**
- 90-day pilot starts. Weekly check-ins with the SIU lead.
- Deliverables: day 30 first ranked queue; day 60 refined queue + 3 case write-ups; day 90 outcomes report with adopt/extend/end decision.

**Total elapsed: 22–40 weeks to pilot kickoff for a vendor without SOC 2.** Production contract follows pilot success in another 8–16 weeks. The wedge year is one production deal, not three.

---

## Funnel math — Phase 1 outbound assumptions

Stage gates without conversion rates mean you can't tell at week 6 whether the funnel is broken at outreach, discovery, security, or pricing.

| Stage | Assumed conversion | At 5 emails/wk × 13 wks = 65 emails | At 20 emails/wk × 13 wks = 260 emails |
|---|---|---|---|
| Cold email → reply | 5–10% | ~5 replies | ~20 replies |
| Reply → discovery call | ~30% | ~1–2 calls | ~6 calls |
| Discovery → proposal | ~50% | ~1 proposal | ~3 proposals |
| Proposal → pilot | ~25% | ~0.25 pilots (i.e., probably zero) | ~0.75 pilots (still <1) |

**Conclusion:** 5 emails/week is not enough to land 1 pilot from cold outbound alone. **Pick one:**
- **Option A — Raise outbound volume to 20/week** (≥6 hours/week of outreach time blocked Tue/Thu).
- **Option B — Shift to warm-channel-only** and reframe the activity metric as **meetings booked, not emails sent.** Target: 2 SIU discovery calls per month, sourced from NHCAA + HCCA + warm intros.

Default recommendation: **Option B with Option A as a backstop after month 3** if warm channels alone aren't producing 2 meetings/month.

---

## Demand generation formula

Three channels, each with a quarterly target:

| Channel | Cadence | Expected output per quarter |
|---|---|---|
| **Outbound cold email** | 5–20/wk to named MCO SIU leads (see funnel math above) | ~1 discovery call per 30 emails → 2–9 calls/qtr depending on volume |
| **Conference warm** | NHCAA Annual Training (Nov), AHIP Medicare/Medicaid (Mar), HCCA Compliance Institute (Apr), regional HCCA chapter meetings monthly | 2–3 qualified discovery calls per major conference |
| **Content / credibility** | One OIG-cited or methods-grounded blog post per month, plus public methods note (see cross-cutting work) | First qualified inbound by month 4–6; compounds slowly |

**~150 MCO SIU leads exist nationally.** At 20 emails/week with no second-wave channel the segment is saturated in ~30 weeks. Conference + content are not optional; they are how you stay in front of the same 150 people without burning the list.

---

## What kills this plan

- **Phase 0 calls never happen, and the whole pack is built on guesses.** Mitigation: this is gate #1. Phase 1 does not fire until 5+ logged calls exist.
- **Dave can't get a warm intro and cold outreach gets ignored.** Mitigation: attend NHCAA Annual Training Conference (Nov) in person — every MCO SIU lead in the country is there. Worth the ~$1,500.
- **All three MCOs have already standardized on a competing detection tool.** Mitigation: discovery calls surface this in week 4–6; if all three are locked in, the wedge thesis is wrong and you pivot to consulting-firm partnership (separate document).
- **Pilot proposal asks for live PHI before MCO is comfortable.** Mitigation: pilot runs on the MCO's *own* claims extract delivered via SFTP to an MCO-controlled storage bucket; MFI never holds the data outside their infrastructure (this is the stateless-DuckDB-on-Parquet model — already true of MFI's architecture).
- **Security review kills the deal in week 12.** Mitigation: start security review in Phase 1 in parallel with discovery, not Phase 4 sequentially. Pre-fill SIG Lite / AHA VSRA v6 and ship with security one-pager. Begin SOC 2 Type II readiness work now even if certification is 6–12 months out — compensating-controls package is the bridge.
- **You hate selling and don't make the calls.** Mitigation: nothing in this document fires without scheduled outreach time. Block Tue/Thu mornings. Track in a sheet. If activity slips for 2 consecutive weeks, the whole plan is paused for re-evaluation, not quietly continued.

---

## What this commits you to — WHEN the campaign reactivates

> Until a T1–T4 trigger fires per `README.md`, none of these commitments are live. The list below is what becomes active **the day a trigger fires**.

- **Re-read `README.md` and confirm the trigger.** Document which trigger fired, when, and the evidence (OIG response email, friend's case write-up, news article, etc.). Update README to flip campaign status from PAUSED to ACTIVE.
- **Run CareSource + AmeriHealth Caritas + Molina in parallel from week 1** — single-thread the segment (MCO SIU), multi-thread the accounts. Zero state PI outreach during the 90-day wedge window.
- **Multi-thread each account from week 1**: champion (SIU), economic buyer (VP Medical Economics / CFO), security (CISO / Vendor Risk), procurement (MSA office). Buyer map is the stakeholder checklist.
- The pilot pitch + security one-pager + outreach sequence are already authored — tailor the `{{placeholders}}` and send. Do not over-rewrite before sending.
- Skipping NHCAA membership decisions, federal OIG conferences, and any state RFP response work during the wedge window (NHCAA *attendance* in Nov is the exception — that's the warm-intro channel).
- Re-evaluating in 90 days post-launch if no discovery call lands. If three MCO SIUs (CareSource, AmeriHealth, Molina) all reject in parallel, the wedge thesis is wrong and you need a different segment (most likely: consulting-firm partnership as a layer in their state PI engagements — separate document).

## What this commits you to — RIGHT NOW (dogfood phase)

- **No outbound to MCO SIUs.** No cold emails, no LinkedIn DMs, no pitch PDFs. The pack stays in the drawer.
- **One paid 90-min session with the investigator friend.** Schedule it. He drives. Two outputs: gaps list + tip-quality assessment.
- **Submit one HHS-OIG Hotline tip using MFI as it exists today.** Walk the full workflow. The friction is the next backlog.
- **Ship the OIG-Hotline-export feature next.** Highest-leverage product work given Dave-as-tipster is now the user.
- **Build the `/methods` page.** All 18 signals, with the precision-at-50 numbers from `feedback_tracker.py` dispositions.
- **Log every tip in `pitch/tips-log.md`** so T1 has an evidence file when an OIG/MFCU response arrives.
