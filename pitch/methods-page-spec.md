> # ⚠️ SUPERSEDED — FEATURE ALREADY SHIPPED (audit 2026-07-05)
> This spec was written against a stale gap list. The /methods page **already exists and is live**
> (`backend/routes/methods.py`, `frontend/src/pages/Methods.tsx`, v3.2.2): public, no-auth, all 18
> signals + citations + provenance + composite note. **One deliberate design difference vs this spec:**
> per-signal precision is **auth-gated** (v3.3.5) — public methodology, authed-only precision, so
> adversarial providers don't get a which-signals-are-weakest roadmap. That supersedes §2.4's
> public-table design. T3(b) is DONE; T3(c) now only needs enough analyst dispositions for ≥6
> signals to show numbers. Kept for the labeling rules + acceptance-criteria language only.

# Spec — Public `/methods` Page (T3 blocker b)

> **Why this exists:** Sales-readiness trigger **T3** requires (a) OIG-Hotline export, (b) this public `/methods` page, and (c) a labeled precision-at-50 number on ≥6 of the 18 signals — all live on `medicaid-inspector.web.app`. The data for (b) and (c) **already exists in code** (`narrative_generator._SIGNAL_META` for per-signal explanations + citations; `feedback_tracker.get_feedback_summary()` for per-signal precision). This page is a publishing job, not a research job.
>
> **Audience:** the data scientist embedded in a PI unit / MCO SIU who reads methodology line-by-line (the most influential detection-vendor evaluator), plus any AG-office reviewer who asks "why did the system flag this provider?" Secondary: OIG/MFCU analysts who receive Dave's tips and want to know the method behind them.
>
> Status: SPEC — drafted 2026-07-05. Owner: Dave.

---

## 1. Route & access

- **Public, unauthenticated**: `https://medicaid-inspector.web.app/methods`
- Frontend: new React page `frontend/src/pages/MethodsPage.tsx`, added to the public router (outside the auth gate — everything else stays gated).
- Backend: new **unauthenticated, read-only** endpoint `GET /api/methods` (new `backend/routes/methods.py`) returning a sanitized JSON document (schema §4). No PHI, no provider identifiers, no raw claims — it publishes *metadata about the method*, nothing about subjects.

## 2. Page content (top to bottom)

### 2.1 Header
- Title: **"Detection Methodology"**
- The canonical line: *"Production fraud-detection platform for Medicaid provider data."*
- One-paragraph method summary — use exactly this framing (brand rule: never "AI-powered"):
  > "Medicaid Inspector applies **statistical anomaly detection + rule-based signals + composite weighted scoring + template-based narrative generation** to the HHS 'Medicaid Provider Spending by HCPCS' dataset (T-MSIS-derived, ~227M rows, 2018–2024). Every signal carries the federal regulation it is designed to surface evidence toward. The composite score is a **rank, not a calibrated probability** — 80/100 does not mean '80% likely fraud.'"

### 2.2 Data source & honest limits (non-negotiable section)
Publish the data-limits paragraph verbatim-equivalent — the same disclosures made in tips:
- Source: HHS *Medicaid Provider Spending by HCPCS* (Feb 2026 release, T-MSIS-derived; free, no DUA). Mirror: `huggingface.co/datasets/HHS-Official/medicaid-provider-spending`.
- Coverage: outpatient/professional claims only — **no inpatient, no pharmacy, no LTC/transport, no diagnoses or modifiers**.
- Suppression: rows under 12 claims are suppressed at source; `ghost_billing` reasons about the suppression floor explicitly.
- Managed-care completeness varies by state; ~6 states had unusable 2024 spend.
- Rows missing either NPI are filtered (they carry inflated capitation dollars).
- One signal (`diagnosis_procedure_mismatch`) currently uses CMS Medicare MUP-by-Provider as a diagnosis-prevalence proxy — flagged for re-basing; its precision row makes its status visible.

### 2.3 The 18 signals — one card per signal
For each signal, rendered from `/api/methods` (sourced from `_SIGNAL_META`):
| Field | Source |
|---|---|
| Signal name + plain-English "what it detects" | `_SIGNAL_META` |
| Detection logic summary (threshold family, peer-group basis) — 2–3 sentences, no exact threshold constants (see §5) | `_SIGNAL_META` + hand-written |
| Regulatory citations (CFR / USC / OIG source per signal) | `_SIGNAL_META` |
| **Precision** (labeled, see 2.4) | `feedback_tracker` |

### 2.4 Precision reporting — the T3(c) requirement
From `get_feedback_summary()` → `signal_stats[]` (`signal`, `true_positives`, `false_positives`, `precision`, multiplier):
- Publish a table: **signal · dispositions reviewed (TP+FP) · precision · weight status** (full / dampened).
- **Labeling rule:** only signals with ≥5 dispositions (the tracker's existing observation floor) show a number; below the floor show *"insufficient dispositions (n<5)"* — never a number. T3(c) is satisfied when **≥6 signals** show a real number.
- **Label the metric honestly:** *"Precision of reviewed flags: of the flags a human analyst dispositioned, the share confirmed worth pursuing. This is not recall, and not a fraud-conviction rate."* If the current disposition set is Dave-as-tipster reviews, say exactly that: *"Dispositions to date are from the founder's own tip-preparation review workflow."*
- Include `updated_at` so staleness is visible.

### 2.5 Composite scoring
- Weighted composite capped at 100; weights dampened by observed per-signal precision (multiplier 0.5–1.0, floor 0.5 so no signal is silently suppressed).
- Repeat the rank-not-probability disclaimer.

### 2.6 From flag to referral (credibility close)
Short section: ranked queue → analyst review → template-based narrative (7 sections, mirrors OIG MFCU referral format, **not LLM — zero hallucination risk**) → evidence chain-of-custody (SHA-256, custody log) → MFCU/OIG referral workflow. One sentence each; link nothing that requires auth.

### 2.7 Footer
Contact for methodology questions + "This page describes method. No provider is named anywhere on it."

## 3. What must NOT appear (brand + legal guardrails)
- ❌ No provider names/NPIs, no real screenshots with identifiers, no example rows.
- ❌ No "AI catches fraud," no "accuracy" absolutes, no recall claims (untracked), no recovery promises.
- ❌ No exact threshold constants (§5), no uncertified compliance claims (HIPAA-aware logging: yes; SOC 2/HITRUST: no).

## 4. `/api/methods` response schema (sketch)
```json
{
  "updated_at": "ISO-8601",
  "dataset": { "name": "...", "rows": 227000000, "years": "2018-2024", "limits": ["..."] },
  "scoring": { "type": "weighted-composite-rank", "cap": 100, "dampening": "precision-based 0.5-1.0" },
  "signals": [
    { "key": "billing_concentration", "title": "...", "detects": "...", "logic_summary": "...",
      "citations": ["42 CFR § 455.23", "..."],
      "precision": { "n": 12, "value": 0.75, "status": "reported" } | { "n": 3, "status": "insufficient" },
      "weight_status": "full" | "dampened" }
  ]
}
```

## 5. Gaming-resistance decision
Publish the *family* of each detection ("claims-per-beneficiary vs. specialty peer distribution"), **not** exact cutoffs/percentile constants. Rationale line for the page: *"We publish what each signal measures and why it is regulatorily relevant; we do not publish exact thresholds, which would be a how-to for evading them."* This keeps the AG-readable promise without handing providers an evasion manual.

## 6. Acceptance criteria (T3-b/c done when…)
1. `/methods` renders publicly (no auth) on `medicaid-inspector.web.app`, mobile-usable.
2. All 18 signals render with citations from `_SIGNAL_META` (single source of truth — no hand-copied citation text).
3. Precision table shows real numbers for ≥6 signals with the honest label + n-floor rule.
4. Data-limits section present, matching tip disclosures.
5. No provider identifier anywhere in page or API payload.
6. `security-compliance-onepager.md` + `pilot-pitch-caresource.md` blockers referencing the missing methods note are updated to point at the live URL.

## Effort estimate
Backend route (serialize `_SIGNAL_META` + feedback summary, sanitize): ~2–3 h. Frontend page: ~3–4 h. Copy pass with brand guardrails: ~1 h. **~1 day total.**
