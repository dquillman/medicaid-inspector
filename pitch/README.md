# pitch/

Sales-side artifacts for Medicaid Inspector's wedge sales motion. Not deployed; not part of the app build.

---

## 🛑 Campaign status: PAUSED (as of 2026-05-29)

**Strategic stance:** Solo-founder dogfood mode. Dave is the user. MFI is being used to identify Medicaid fraud and submit tips to **HHS-OIG Hotline** (`tips.oig.hhs.gov`) and **state MFCUs**. The MCO SIU sales campaign is in the drawer until a readiness trigger fires.

### Sales-readiness triggers — any ONE fires the campaign

| # | Trigger | Evidence required |
|---|---|---|
| **T1** | Submitted tips have produced ≥1 OIG or MFCU response indicating action | Email, letter, or call from OIG/MFCU other than "closed, no action" — a follow-up question, a request for more info, a confirmation an investigation has been opened, or anything implying the tip is being worked. Log the response with date + sender + what was asked. |
| **T2** | The investigator friend has used MFI to triage at least one real case in his own job and reports it beat his spreadsheet workflow | A written or recorded statement from the friend confirming MFI surfaced a lead his spreadsheet workflow would have missed, or worked the lead measurably faster. Pay him for the time. |
| **T3** | MFI has shipped (a) the OIG-Hotline-export feature, (b) the public `/methods` page, AND (c) a labeled precision-at-50 number on at least 6 of the 18 signals | All three live on `medicaid-inspector.web.app`. The precision-at-50 numbers are computed against `feedback_tracker.py` dispositions (or another labeled set) and visible in the app + on the methods page. |
| **T4** | A fraud case MFI flagged hits the news independently of any tip Dave filed | DOJ press release, state AG enforcement announcement, OIG report, or major-press investigation that names a provider MFI's queue already ranked. Cross-reference and timestamp it. |

When any one of these fires:
1. Update this README — move campaign status from PAUSED to ACTIVE
2. Re-read `wedge-buyer-rationale.md` (the strategy may have shifted while the campaign was paused; the ICP scorecards, buyer map, and funnel math are still valid)
3. Begin Phase 1 outreach per the wedge doc — CareSource + AmeriHealth Caritas + Molina in parallel
4. The pitch pack as currently authored is the artifact set; tailor and send

**Until a trigger fires:** no outbound, no cold emails, no pitch PDFs sent. The artifacts live here as a ready-to-fire reserve, not an active campaign.

---

## Files

| File | Purpose | Status |
|---|---|---|
| [`wedge-buyer-rationale.md`](./wedge-buyer-rationale.md) | Strategic decision: MCO SIU > State PI; CareSource primary, AmeriHealth + Molina in parallel. ICP scorecards (MCO + persona), 10-question discovery qualifying matrix, buyer-map, funnel math, demand-gen formula | RESERVE — gated on T1-T4 trigger |
| [`pilot-pitch-caresource.md`](./pilot-pitch-caresource.md) | 90-day fixed-price ($45K) pilot proposal — telefraud-DME cold open, data-provenance disclosure, AG/MFCU chain-of-custody section, six signals with OIG backing, explicit no-promise list | RESERVE — gated on T1-T4 trigger |
| [`security-compliance-onepager.md`](./security-compliance-onepager.md) | One-page security & compliance for MCO InfoSec reviewers. Glossary, public methods note, honest cert posture, SOC 2 bridge mechanisms, source-code escrow language | RESERVE — gated on T1-T4 trigger |
| [`outreach-sequence.md`](./outreach-sequence.md) | 5-touch cold-outbound sequence + 7-source name-discovery + A/B matrix + 23-column tracking sheet + 8 discipline rules | RESERVE — gated on T1-T4 trigger |

---

## What IS active right now (dogfood phase)

The work this week and ongoing — none of it requires the sales pack:

1. **Use MFI to submit one tip to HHS-OIG Hotline** (`tips.oig.hhs.gov`). Highest-confidence flagged provider. Walk the full submission flow end-to-end. Note every place MFI doesn't yet output what the form wants. That delta becomes the next product backlog.
2. **Run the structured 90-minute session with the investigator friend.** He drives. You watch. Two outputs: (a) the list of every gap between MFI and his actual workflow, (b) his read on whether MFI's current dossier export is tip-quality for OIG/MFCU triage. Pay him for the time. This work also counts toward T2.
3. **Ship the OIG-Hotline-export feature.** One-click conversion of a flagged provider into an OIG Hotline submission packet — allegation summary, providers involved, evidence index, methodology citation, attachable PDF. This is the highest-leverage product feature given the current user is Dave-as-tipster. Counts toward T3.
4. **Build the `/methods` page.** For each of the 18 signals: cohort definition, threshold, holdout precision-at-50, false-positive rate, last-calibrated date, known limitations. Counts toward T3.
5. **Log every tip submitted** in `pitch/tips-log.md` (create when first tip ships): date, target provider (anonymized externally), signals invoked, submission method (OIG Hotline / state MFCU / both), response received (if any). This log is the evidence file for T1.

---

## What's NOT in this directory yet (deliberately)

- **`tips-log.md`** — create when first tip is filed. Format: date, target (anonymized), signals invoked, submission channel, response received.
- Master Services Agreement template — wait until first pilot is signed; do not over-engineer
- Case study — requires actual pilot data (or, alternatively, an OIG-cited case)
- Pricing tiers for production contracts — set during pilot wrap-up
- Investor deck — different audience, different document, different time
- Public methods note (`medicaid-inspector.web.app/methods`) — referenced by `pilot-pitch-caresource.md` and `security-compliance-onepager.md`; **part of T3**

---

## Pitch-pack hardening history

| Date | Pass | What changed |
|---|---|---|
| 2026-05-28 | v1 draft | Initial wedge decision, pilot proposal, security one-pager, README — written from secondary research only |
| 2026-05-29 | v2 ultracode hardening | 5-advisor adversarial review (Pahlka, Slavitt, Brennan, Roberge, Levie) + 4-stat fact-check + per-file rewrite. Added Phase 0 gating, telefraud-DME cold open, data-provenance disclosure, AG/MFCU/defense-attorney chain-of-custody section, glossary across all docs, SOC 2 bridge mechanisms, succession/escrow language, 5-touch outreach sequence with A/B matrix |
| 2026-05-29 | v3 strategic pivot | Friend revealed (a) line investigators use Excel, (b) suggested Dave use MFI to submit own whistleblower tips. Dave declined qui tam (lawyer-aversion). Pivot: campaign PAUSED, Dave-as-tipster mode active, sales pack moved to RESERVE behind T1–T4 readiness triggers. Phase 0 (5-10 SIU discovery calls) superseded — friend session collapses Phase 0 |
