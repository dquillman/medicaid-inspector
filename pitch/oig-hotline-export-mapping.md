# Spec — HHS-OIG Hotline Export (T3 blocker a)

> **Why this exists:** Trigger **T3** requires an OIG-Hotline-export feature. The narrative generator already produces a 7-section MFCU-style package (`services/narrative_generator.py`), but the **HHS-OIG Hotline (`tips.oig.hhs.gov`) is a web form with its own fields and length limits** — it doesn't accept a referral PDF. Today Dave hand-carves each tip out of the narrative; this spec defines a `Hotline Export` view that emits one copy-paste-ready block per hotline field. It is also the highest-leverage dogfood feature: every tip filed through it feeds `pitch/tips-log.md` and therefore trigger **T1**.
>
> **Honesty flag:** the hotline form's exact field names/limits are **[VERIFY-AT-SUBMISSION]** — the form is behind a JS wizard and can change. On the next real tip, walk the live form and correct the right-hand column below; do not treat this table as gospel until then. The narrative-side (left column) IS verified against the generator.
>
> Status: SPEC — drafted 2026-07-05. Owner: Dave.

---

## 1. Source material (verified in code)

`generate_narrative(npi)` produces sections:
(a) **Subject Identification** · (b) **Billing Summary** · (c) Risk Assessment · (d) Signal Findings · (e) Patterns of Concern · (f) Recommended Actions · (g) Citations · (h) Review Status (optional).

Supporting endpoints already shipped: evidence chain-of-custody (SHA-256 + custody log), signal evidence cards, HTML report export.

## 2. Field mapping — narrative → hotline form

| Hotline form area **[VERIFY-AT-SUBMISSION]** | What MFI emits | Source | Notes / transforms |
|---|---|---|---|
| **Who is the complaint about?** — subject name, business name, address, phone, provider type | Provider legal/business name, NPI, NPPES practice address, enrolled specialty | Section (a) Subject Identification | Include NPI in the name field's text if no dedicated NPI field exists ("… , NPI 1XXXXXXXXX"). |
| **Category of wrongdoing** | "Medicaid — provider fraud (billing)" + the dominant pattern label | Sections (d)/(e) | Map cross-signal pattern → hotline category words: phantom-billing → "billing for services not rendered"; upcoding_pattern → "billing for more expensive services than provided"; ghost/bene-concentration → "billing for services not rendered"; shell/identity → "kickback/ownership misrepresentation" (pick closest available option on the live form). |
| **Describe the allegation** (main narrative box; expect a hard char limit, likely 2–4K **[VERIFY]**) | The **Tip Summary** — a NEW compact rendering (§3) compressing (b)+(d)+(e) into ~1,800 chars | (b), (d), (e) | Must lead with the 2–3 strongest signals, with numbers ("Provider billed $X across Y claims for Z beneficiaries in period …; claims-per-beneficiary N× the specialty peer mean"). Plain prose, no markdown, no tables. |
| **When did it occur / time period** | `CLAIM_FROM_MONTH` min–max of the flagged activity window | (b) | e.g. "2021-03 through 2024-06". |
| **Estimated dollar amount** | Total paid over the flagged window (conservative: flagged-code subset, not provider total) | (b) | State the basis in the description: "≈$X in Medicaid payments over the window (public HHS spending data)". Never present as 'proven loss'. |
| **How did you become aware?** | Standard sentence: "Analysis of the public HHS 'Medicaid Provider Spending by HCPCS' dataset (T-MSIS-derived) using statistical anomaly screening; methodology at medicaid-inspector.web.app/methods." | static + /methods URL | This is why the `/methods` page ships with or before this feature. |
| **Supporting documents?** | "Yes — detailed analysis available on request", plus the HTML report if the form takes uploads **[VERIFY upload types/size]** | HTML report export | If uploads are accepted: attach the report with fake-name screenshot rules N/A (real subject is appropriate *in a tip*, unlike marketing). Evidence files carry SHA-256 from the custody store. |
| **Data caveats** (fold into description tail) | Fixed disclosure sentence (§4) | static | REQUIRED in every tip — protects credibility, matches skill/brand rules. |
| **Your info / anonymity choice** | Not exported — Dave chooses per tip on the form | — | Export deliberately excludes reporter identity. |

## 3. New artifact: the **Tip Summary** renderer

Add `render_hotline_tip(npi) -> dict` in `narrative_generator.py` (reuses section builders; template-based, no LLM):

```json
{
  "subject": "…name, NPI, address, specialty…",
  "category_hint": "billing for services not rendered",
  "allegation_text": "≤1800 chars, plain prose, strongest 2-3 signals with numbers",
  "period": "2021-03 to 2024-06",
  "est_dollars": 1234567,
  "aware_text": "Analysis of the public HHS …",
  "caveat_text": "This analysis is based on …",
  "citations": ["42 CFR § 455.23", "…"]
}
```

Frontend: a **"Hotline Export"** tab on the provider/report page rendering each field as a labeled copy-button block, in the same order as the OIG wizard, with live char counts (limit constants in config so they're correctable after [VERIFY]). One click per box → paste into the form. No auto-submission — the hotline is a human act.

## 4. Fixed caveat sentence (ship verbatim, editable in config)

> "This analysis is based on the public HHS Medicaid Provider Spending dataset (outpatient/professional claims only; no inpatient, pharmacy, or long-term-care claims; no diagnoses; small-volume rows suppressed at source; managed-care completeness varies by state). Figures are statistical indicators of anomalous billing, not proof of fraud; the composite score ranks anomalousness and is not a probability."

## 5. Tie-in to T1 evidence — `pitch/tips-log.md`

On every export, append (or prompt to append) a row:

| Date | NPI (masked in log: 1XXX…) | Pattern lead | Est. $ | Channel (OIG / state MFCU) | Confirmation # | Response? |
|---|---|---|---|---|---|---|

T1 fires on the first **Response?** entry that isn't "closed, no action." The log file does not exist yet — create it with this header on first export.

## 6. Acceptance criteria
1. From any flagged provider: Hotline Export tab renders all §2 fields with copy buttons + char counts.
2. `allegation_text` ≤ configured limit, leads with quantified strongest signals, ends with the §4 caveat.
3. Every export offers the tips-log append.
4. Field labels/limits corrected against the live form after the first real submission ([VERIFY] tags removed from this doc).
5. State-MFCU variant: same renderer, per-state address/portal noted in the log (MFCU portals differ; do not over-engineer — OIG first).

## Effort estimate
`render_hotline_tip` (reusing section builders): ~3 h. Frontend export tab: ~3 h. Tips-log scaffold: ~0.5 h. **~1 day total.** Ship after (or with) `/methods` — the "how did you become aware" line wants that URL live.
