# Outreach Sequence — CareSource SIU Wedge

> **Status: TEMPLATE — gated on Phase 0.** This sequence does not fire until `wedge-buyer-rationale.md`'s "What we've validated" table has 5+ logged SIU discovery calls. The version below is the cold-outbound fallback once warm channels (Option B in the wedge doc) have produced fewer than 2 meetings/month for two consecutive months.
>
> **Owner:** Dave · **Last updated:** 2026-05-29 · **First-20-prospect data review:** scheduled 30 days after first send.
>
> No emoji. No "I hope this finds you well." No "synergy," "leverage," "circle back," or "touch base." Every paragraph earns its place. Every ask is specific. Reading time of the entire sequence per prospect is under four minutes — that is the budget.

---

## Identifying the right person to contact

**Primary target title (in priority order):**

1. *VP, Special Investigations* (CareSource-specific)
2. *Director, Special Investigations Unit*
3. *Director, Program Integrity*
4. *Director, Fraud, Waste & Abuse* (sometimes "FWA Director")
5. *AVP, Payment Integrity*

Title vocabulary inside MCOs is inconsistent — "Program Integrity" at one MCO is "Payment Integrity" at the next, and "Special Investigations" sometimes lives under Compliance and sometimes under Medical Economics. Search all five before concluding the person doesn't exist.

**Step-by-step name discovery:**

1. **LinkedIn (primary).** Run these exact searches in LinkedIn (signed in, all-filters):
   - `"CareSource" AND "Special Investigations"` — current company filter set to CareSource
   - `"CareSource" AND "Program Integrity"` — current company filter set to CareSource
   - `"CareSource" AND ("FWA" OR "fraud waste abuse")` — current company filter
   - `"CareSource" AND "Payment Integrity"` — current company filter
   - For each result, capture: name, exact title, tenure-in-role (the "X yrs Y mos" line), prior role, mutual connections. Tenure-in-role drives persona-fit scoring per `wedge-buyer-rationale.md` (target 6–24 months).
2. **NHCAA member directory.** Log into the NHCAA member portal (or borrow access from a member). Filter member list by organization "CareSource." Cross-reference names with LinkedIn results — anyone listed in both is a confirmed practitioner, not just a title-holder.
3. **HCCA (Healthcare Compliance Association) chapter rosters.** Ohio HCCA chapter publishes member rosters at chapter meetings. CareSource compliance staff appear regularly. Names captured here are warm-up contacts (see backup paths below).
4. **AHIP attendee lists.** AHIP's Medicare/Medicaid/Duals conference (typically March) publishes attendee lists to registrants. CareSource SIU and Program Integrity staff routinely attend.
5. **CareSource press releases & SEC-adjacent filings.** CareSource is a nonprofit so no SEC filings, but their 990 (IRS Form 990, publicly searchable via ProPublica Nonprofit Explorer or GuideStar) lists key employees and compensation. Cross-reference against LinkedIn to identify the SIU/PI leadership chain.
6. **Federal court PACER + DOJ press releases.** Search recent (last 24 months) Medicaid fraud civil settlements and criminal indictments where CareSource was the referring MCO. The SIU lead is often named in DOJ press releases as the affidavit signer. This is the highest-signal way to find a real practitioner, not a title-holder.
7. **Conference speaker lists.** NHCAA Annual Training (November), AHIP, HCCA Compliance Institute (April). Check 2024 and 2025 speaker rosters at `nhcaa.org`, `ahip.org`, `hcca-info.org` for any CareSource-affiliated speaker on SIU, payment integrity, or fraud-analytics topics.

**Backup contact paths (use as warm-up, not as substitute):**

- *SIU Manager* or *Senior SIU Investigator* — a manager-tier contact is a legitimate landing point if the VP is unreachable. They cannot sign a $45K SOW but they can introduce you internally, and their feedback on the methodology is the second-best version of a Phase 0 call.
- *Compliance Officer* or *VP Compliance* — at CareSource, SIU sometimes reports through Compliance. A compliance officer can route a credible vendor inquiry to the right person inside a week.
- *Director, Medical Economics* or *VP, Government Programs* — the economic-buyer side of the buyer map (see `wedge-buyer-rationale.md`). Reaching the economic buyer first inverts the normal sequence, but for a vendor with a pricing-and-ROI story it can work. Only use this path if the SIU side is dark for 30+ days.
- *Vendor Risk Management lead* / *Third-Party Risk* — sending the security one-pager + pre-filled SIG Lite / AHA VSRA v6 here in parallel starts the security clock and creates a paper trail the SIU lead will see when they eventually circle back internally. This is not outreach — it is parallel-pathing per Phase 1 of the wedge doc.

**Do not contact:**
- *CEO* or *Chief Medical Officer* of CareSource. Too senior, will get routed to a junior analyst on the way down, burns the eventual ask.
- *Procurement* as the first touch. They cannot say yes; they can only say no.
- *External PR / Communications.* They will treat this as a media inquiry.

**Stop-loss rule:** If you cannot identify a named SIU/PI/Payment-Integrity leader at CareSource within 90 minutes of focused searching across the seven sources above, the title structure is opaque enough that cold outbound will fail. Pivot immediately to NHCAA conference attendance (November) as the warm-intro channel and tag this prospect as "conference-warm-only."

---

## Touch 1 — Cold email (Day 0)

**Subject (primary):** Six-signal Medicaid provider scoring — 30-min look?

**Body (under 120 words):**

> {{First name}},
>
> I run Medicaid Inspector, a six-signal fraud-detection layer that scores 106,660 providers against address co-location, corporate-shell ownership, peer-relative claims anomalies, upcoding distribution, beneficiary concentration, and OIG LEIE matches. It is built to sit alongside an SIU's existing case-management system, not replace it.
>
> The reason I am writing you specifically: CareSource's Medicaid-dominant book and seven-state contract footprint is the exact profile we built the tool for. I am not asking for a pilot. I am asking for 30 minutes to walk you through the methodology and hear which of the six signals maps to a detection gap your current toolchain doesn't close.
>
> One attachment: our security and compliance one-pager. BAA-ready, HIPAA-aware audit logging, customer-tenant data model.
>
> Thirty minutes next week?
>
> Dave Quillman
> Medicaid Inspector · medicaid-inspector.web.app
> dquillman2112@gmail.com · {{phone}}

**Attachment:** `security-compliance-onepager.md` (rendered as PDF). One attachment, no deck.

**Three subject-line variants for A/B (rotate per cohort of 5 prospects):**

- A — *Six-signal Medicaid provider scoring — 30-min look?* (methodology-forward)
- B — *Address-clustering pattern in your Ohio Medicaid book — worth 30 min?* (signal-forward, named to their state)
- C — *Question from a Medicaid fraud-detection founder — 30 min?* (curiosity-forward, lowest-claim)

Track open rate per variant; reply rate is the only metric that matters.

---

## Touch 2 — LinkedIn connection note (Day 3 if no response)

**Send with connection request. Under 300 chars.**

> {{First name}} — emailed Monday on a six-signal Medicaid detection layer we built. Different angle here: noticed CareSource Ohio recently {{specific public event — e.g., "renewed the OH Medicaid managed-care contract through 2028" or "expanded D-SNP coverage"}}. Curious how SIU is staffing for the panel growth. No pitch — happy to share what we are seeing in OH provider data. — Dave

**Tailoring rule:** the `{{specific public event}}` slot must reference a real, recent, public CareSource news item — Medicaid contract renewal, state expansion, plan-line change, OIG settlement they were involved in, a CareSource SIU-staff conference talk. If you cannot find one within 5 minutes, do not send the LinkedIn touch. Generic LinkedIn notes are worse than no LinkedIn note.

---

## Touch 3 — Follow-up email with a value-add (Day 7)

**Subject:** Pattern we are seeing in Ohio Medicaid DME — for your queue

**Body:**

> {{First name}},
>
> Following up on the note from {{date of Touch 1}}. Not asking for a meeting in this one — just sharing one finding from our public-data work that may be useful to your queue.
>
> Across the Ohio active-billing provider set we score, the address-cluster signal surfaces a recurring pattern in the DME and telehealth-prescribing space: small clusters of 5–9 DME supplier NPIs sharing a single normalized street address, with one common authorized official in the NPPES record, billing concentrated against a small set of physician NPIs who appear across multiple clusters. This is the OIG telefraud-DME pattern (Special Fraud Alert 2022, Operation Rubber Stamp) operationalized as a queryable signal.
>
> If your existing toolchain does not surface address-cluster + corporate-shell together, the joined-signal view is where the high-precision leads tend to live. Happy to walk you through the methodology and the cohort definitions we use. Same 30-min ask.
>
> Dave
> Medicaid Inspector

**Important:** the finding above is a methodology summary, not provider-identifying detail. Per `mfi-context` anti-patterns: no real provider names, no real NPIs, no real addresses leave this email. If a recipient asks for specifics, the answer is "I'll show you live in the 30 minutes" — not a follow-up email with PHI-adjacent data.

---

## Touch 4 — Voicemail script (Day 12)

**Under 30 seconds when read aloud at a normal pace. Practice it.**

> Hi {{First name}}, this is Dave Quillman with Medicaid Inspector — emailed you on {{Touch 1 date}} and again on {{Touch 3 date}} about a six-signal Medicaid provider-scoring tool we built. I am not chasing for a pitch. I am asking for thirty minutes so you can tell me where our methodology breaks against your real queue. If that is worth the time, my number is {{phone}} — again, {{phone, repeated slowly}}. Either way, thanks for the read. Dave Quillman, Medicaid Inspector.

**Rules:**
- Phone number stated twice, second time slowly. Voicemail transcription tools mangle digits.
- No "just following up." Reference both prior touches by date.
- No question in the voicemail. A voicemail that ends in a question creates pressure; a voicemail that ends in "either way, thanks for the read" creates none and gets returned more often.

---

## Touch 5 — Break-up email (Day 18)

**Subject:** Closing the loop — CareSource SIU

**Body (under 80 words):**

> {{First name}},
>
> Reached out three times over the last two and a half weeks and want to respect your inbox. Closing the loop here.
>
> If a six-signal Medicaid provider-scoring layer becomes interesting later — or if you'd just like a copy of what we publish on the methodology — reply with one word and I will send it.
>
> I will circle back in Q4 ahead of NHCAA Annual Training, in case the timing then is better.
>
> Dave Quillman
> Medicaid Inspector

**Discipline:** Q4 / NHCAA is a specific, dated re-engagement window. Do not write "circle back later" or "stay in touch" — those are dead phrases that signal a generic templated send.

---

## A/B test matrix

**Three subject-line variants × two opening sentences = 6 combinations.** Run the first 20 prospects through the matrix as ~3 per combination so each cell has signal.

**Opening sentence variants:**

- Opener 1 (methodology-led, per April Dunford's "frame the category before the feature"): *"I run Medicaid Inspector, a six-signal fraud-detection layer that scores 106,660 providers against address co-location, corporate-shell ownership, peer-relative claims anomalies, upcoding distribution, beneficiary concentration, and OIG LEIE matches."*
- Opener 2 (account-led, per Mark Roberge's "segment of one"): *"CareSource's Medicaid-dominant book and seven-state contract footprint is the exact profile we built Medicaid Inspector against — a six-signal provider-scoring layer designed to sit alongside an SIU's existing case management."*

**Matrix:**

| Cell | Subject | Opener | Prospects assigned |
|---|---|---|---|
| 1A | A: Six-signal Medicaid provider scoring — 30-min look? | Opener 1 | Prospects 1, 8, 15 |
| 1B | A | Opener 2 | Prospects 2, 9, 16 |
| 2A | B: Address-clustering pattern in your Ohio Medicaid book | Opener 1 | Prospects 3, 10, 17 |
| 2B | B | Opener 2 | Prospects 4, 11, 18 |
| 3A | C: Question from a Medicaid fraud-detection founder | Opener 1 | Prospects 5, 12, 19 |
| 3B | C | Opener 2 | Prospects 6, 13, 20 |

(Prospects 7 and 14 — one wildcard each, founder discretion, to test a one-off variant.)

**Tracking:** in the sheet below, log subject cell + opener cell per prospect. After 20 sends, tally reply rate per cell. **Do not declare a winner before 20 sends.** A 1-of-3 reply on a single cell is noise, not signal — per Roberge, segment ruthlessly before aggregating, but also do not aggregate before you have enough N to segment. Twenty is the floor.

---

## Tracking sheet template

Create a Google Sheet titled `MFI-SIU-Outreach-2026Q2`. One row per prospect. Columns in this order:

| # | Column | Notes |
|---|---|---|
| 1 | Prospect ID | P01, P02, P03 — stable ID for matrix assignment |
| 2 | First name | |
| 3 | Last name | |
| 4 | MCO | CareSource / AmeriHealth Caritas / Molina |
| 5 | Exact title | Verbatim from LinkedIn |
| 6 | Tenure in role (months) | For persona green/yellow/red per wedge doc |
| 7 | Email | |
| 8 | Phone | |
| 9 | LinkedIn URL | |
| 10 | Source channel | LinkedIn / NHCAA / DOJ presser / HCCA / 990 / referral |
| 11 | Subject cell (A/B/C) | |
| 12 | Opener cell (1/2) | |
| 13 | Touch 1 sent (date) | |
| 14 | Touch 2 sent (date) | |
| 15 | Touch 3 sent (date) | |
| 16 | Touch 4 sent (date) | |
| 17 | Touch 5 sent (date) | |
| 18 | Response (Y/N) | |
| 19 | Response touch # | Which touch produced the reply |
| 20 | Response sentiment | Booked / interested-not-now / not-fit / hostile / unsubscribe |
| 21 | Next action | Discovery call date, follow-up date, drop |
| 22 | Disposition | Active / call-booked / dead / re-engage-Q4 |
| 23 | Notes | Free-text — quotes from the reply, intel from LinkedIn, etc. |

**Weekly review:** Friday afternoon, 30 minutes. Update column 22 on every active row. Anyone in "dead" goes into the Q4 re-engage list per Touch 5.

---

## Discipline rules

1. **No more than 5 prospects in active sequence at once.** Per Roberge's "start small, define success criteria, then scale," running 30 prospects in parallel before knowing whether the sequence converts at all is hiring-into-a-wall. Five at a time, until the first 20 are complete and reviewed.
2. **Do not deviate from the script for the first 20 prospects.** No "personalized creative touches," no improvised subject lines, no off-template P.S. lines. The whole point of the matrix is to isolate which variables move reply rate. If every send is a snowflake, the data is uninterpretable.
3. **Stop the sequence the moment a discovery call is booked.** Touches 2–5 are wasted on a booked prospect and risk pushing them out of the calendar slot. Move them to disposition "call-booked" and run discovery per `pilot-pitch-caresource.md`.
4. **If the prospect replies negatively, stop immediately.** No "thanks for the reply" message. Move to disposition "dead." Re-engage only if they appear in the Q4 NHCAA list with a different title.
5. **If no response from any of the first 10 prospects after Touch 5, the wedge thesis or the message is wrong.** Two failure modes to distinguish:
   - **Thesis failure:** wrong segment. The Phase-0 calls in `wedge-buyer-rationale.md` were supposed to validate that MCO SIU is the right wedge. If 10 cold-outbound attempts at CareSource / AmeriHealth / Molina produce zero engagement, the thesis is either wrong (SIU is not the buyer) or under-warmed (cold-only cannot crack this segment).
   - **Message failure:** right segment, wrong words. Reply rate ≤2% across 10 prospects with a tested matrix means the message itself is not landing — most likely the opener positions the category in a way the buyer does not recognize (per Dunford, "weak positioning makes a great product invisible").
   - **Re-evaluation gate:** halt outbound. Run two more Phase-0 discovery calls (per the wedge doc) explicitly testing both hypotheses. Do not resume outbound until the gap is named. See `wedge-buyer-rationale.md` "What kills this plan" for the re-evaluation criteria.
6. **Do not exceed five touches.** A sixth touch is harassment. The Q4 re-engagement in Touch 5 is a separate sequence, not a continuation of this one.
7. **No mass merge of all three MCOs in one batch.** Run CareSource first (the primary per the wedge doc), AmeriHealth second, Molina third — staggered by a week per MCO so that learnings from cell 1A on CareSource can inform whether the same cell is worth running on AmeriHealth.
8. **Activity tracking, not outcome tracking, is the weekly metric.** Per Roberge's leading-indicator discipline: bookings are lagging. The weekly metric is *touches sent on schedule* and *prospects added to sequence*. If activity slips for two consecutive weeks, the whole plan is paused for re-evaluation, not quietly continued (per `wedge-buyer-rationale.md`'s commitment).
