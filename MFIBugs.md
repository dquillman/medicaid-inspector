# MFI Bug Log

## 2026-07-26 — coverage: per-se leads below the scan cutoff (FIXED, v3.52.0)

### 11. The $1M scan cutoff hid provable fraud — FIXED
**Was:** The prescan scores every NPI with $1M+ in lifetime Medicaid payments —
106,660 of 617,503 billing NPIs (17.3% of NPIs, 94.6% of dollars). That is the
right trade for the statistical signals, which need peer stats to mean anything.
It was the wrong trade for the two PER-SE signals: 42 CFR § 1001.1901 has no
dollar threshold, so an OIG-excluded provider billing $200k is exactly as
referable as one billing $2M. Measured: **506 OIG-excluded providers billing
$64.2M were invisible to MFI purely because each billed under $1M.**
**Fix:** `scripts/build_perse_sweep.py` runs the two per-se checks across the
FULL universe (one parquet scan — they need no peer statistics), writing
`perse_leads.json`. Served by `core/perse_store.py` + `routes/perse.py`, and
`/exclusions/excluded` now reads the sweep instead of walking the scan cache.
845 of 1,081 leads sit outside the scan cache.

### 12. `build_deactivations.py` ignored NPPES reactivations — FIXED
**Was:** The builder kept any NPI with a deactivation date, ignoring the
adjacent "NPI Reactivation Date" column. **1,655 of 10,968 (15.1%) had been
reactivated** — many within days (a 2006 NPPES cleanup artifact: deactivated
03/17/2006, reactivated 03/23/2006). Those NPIs are alive, and every one of them
was feeding `dead_npi_billing` as permanently dead.
**Fix:** currently-dead NPIs stay in `npi_deactivations.json`; reactivated ones
move to `npi_deactivation_windows.json` as `{npi: [deact, react]}`, where billing
INSIDE the closed window is still a finding but a narrower one. Combined with
dropping NPIs that billed only *before* deactivation, the raw sweep fell from
10,846 to 1,081 leads — a 90% noise cut.

### 13. LEIE placeholder NPI produced a phantom $4.4M lead — FIXED
**Was:** LEIE writes `0000000000` when it has no NPI for an excluded person. The
Medicaid file has a same-named catch-all bucket, so joining them surfaced a
phantom "$4.4M billed while excluded" lead — ranked **second**. The billing file
also carries state-assigned IDs (e.g. `A430617100`, $139M) that are not NPIs.
**Fix:** the sweep validates `^[12]\d{9}$` before joining.

### 14. Two `ExcludedProvider` interfaces silently merged — FIXED
**Was:** `frontend/src/lib/types.ts` declared `ExcludedProvider` twice. TypeScript
declaration-merges same-named interfaces in a module, so each shape silently
required the other's fields; it only compiled because both are produced by
`get<T>()` casts rather than constructed.
**Fix:** the batch-scan row is now `BatchExcludedProvider`.

### 15. `perse_store` was missing from the test-state redirect — FIXED
**Was:** `tests/conftest.py::_STATE_MODULES` is a hand-maintained list, despite
its own comment claiming a new store "can't quietly start writing real state."
A new store not on the list reads the developer's real files.
**Fix:** added `core.perse_store`. The list remains hand-maintained — a real fix
would enumerate `core.*` instead.


## 2026-07-08 — Referral Packet / export batch (FIXED, v3.7.11)

Reported by Dave via JARVIS/MFI session. Repro NPI: `1720390115`.

### 1. Referral Packet download behaviour — FIXED
**Was:** "Generate Referral Packet" opened the HTML inline in a new tab (`window.open`) instead of saving a file.
**Fix:** `api.referralPacket` (`frontend/src/lib/api.ts`) now downloads the packet via an anchor with `download`, so it saves rather than renders. Users can save/forward for OIG submission.

### 2. Empty HCPCS / timeline sections in exports — FIXED
**Was:** "Top HCPCS Codes Billed" and the monthly timeline rendered blank on the slim-cache deployment (no local parquet; per-code/monthly detail not loaded).
**Fix:** `routes/referral.py` now runs `enrich_provider_detail` (local parquet enrichment when available) and, on the remote-slim path, falls back to the aggregate summary the slim cache carries (`distinct_hcpcs`, `top_hcpcs`) with a visible note — never a silently-empty table. The timeline section shows a note plus the scan-time billing-period bounds (first/last month, active months). The Fraud Package export (`routes/providers.py`) already carried a `DATA_COMPLETENESS_NOTE.txt`; unchanged.
**Note:** Risk score, fraud-signal evidence, and billing totals were always valid (computed at scan time); only the per-code/monthly detail was missing.

### 3. Invalid/special characters in narrative — FIXED
**Was:** The OIG Hotline tip narrative contained non-ASCII typographic characters (en-dash in "2018–2024", etc.) that HHS-OIG's submission form rejects, forcing manual editing.
**Fix:** New `core/text_sanitize.py::to_ascii` maps typographic punctuation to ASCII and drops any residual non-ASCII. `provider_oig_tip` (`routes/providers.py`) sanitizes the narrative text and all free-text fields before returning.

### 4. Dash in Referral Packet file name — FIXED
**Was:** Saving the packet produced a filename with a " - " segment (from the document `<title>`, "... — NPI ...").
**Fix:** The download now uses an explicit, house-style filename: `referral_packet_<npi>.html` (lowercase, underscore-separated, no spaces or dashes).

## 2026-07-09 — HAL field report from deployed instance (FIXED, v3.7.13)

Surfaced by HAL/JARVIS while investigating NPI `1720390115` (Dunlap) on the Cloud Run deployment. HAL could not write these to this log itself (see item 5) — captured here from a local session.

### 5. log_bug crashes on Cloud Run instead of degrading — FIXED
**Was:** The `log_bug` MCP/HAL tool threw `[Errno 13] Permission denied: '/MFIBugs.md'` on the deployed instance. Two defects: (a) `_BACKEND_DIR.parent / "MFIBugs.md"` resolves to the read-only container root `/MFIBugs.md` on Cloud Run; (b) the handler `raise`d on write failure, violating its own "best-effort, degrade gracefully" contract. Ironically, a bug in the bug-logger.
**Fix:** `backend/mcp_server.py` — try the committable repo file, fall back to a writable temp path, and NEVER raise on write failure. When every target is unwritable it returns `logged:false` with the formatted `entry` text so the caller (HAL) can relay it. `persisted` now accurately reflects whether it hit the repo file.

### 6. Temporal Anomaly panel shows generic failure on slim deployment — FIXED
**Was:** On Cloud Run (no local parquet) the Temporal Anomaly Detection panel showed "Could not load temporal analysis." The backend already 404s with an explanatory detail, but the frontend's `errMsg.includes('404')` check never matched (the thrown error carries the FastAPI `detail` string, not the status code), so both the "unavailable here" and "no data" cases fell through to the generic error.
**Fix:** `frontend/src/components/TemporalAnalysisSection.tsx` — match on the detail message: "no billing data" hides the panel; the full-dataset-only case shows an informative note (month-by-month detail isn't loaded here, but ramp/volume anomalies remain captured in the risk score from scan-time summary data). Cosmetic gap, not an analytical one.

### 8. Out-of-subset provider hard-404s on deployment — FIXED (v3.7.14)
**Was:** Looking up an NPI not in the 106,660-scanned subset on the Cloud Run deployment returned "NPI X is not in the scan cache, and on-demand dataset lookups are unavailable on this deployment (remote dataset)" — a dead end shown as a red error. Repro NPI: `1063980332` (CORTNEY DUNLAP LPC LLC).
**Fix:** `backend/routes/providers.py::get_provider_detail` now returns a PARTIAL profile (200, `partial:true`, `in_scan_cache:false`) for out-of-cache NPIs on remote-dataset deployments: live NPPES identity + OIG LEIE / SAM.gov / NPI-status exclusion checks (all resolve on-demand there), with a note that Medicaid billing/risk needs the provider in the scanned subset. `frontend/src/pages/ProviderDetail.tsx` renders a focused partial view (identity + exclusion status + banner) instead of erroring. If NPPES also has no record, still 404s. For a fraud tool, "who is this NPI and are they excluded?" is the useful answer even without Medicaid billing.

### 9. HAL bug-logging not durable on the deployed instance — FIXED (v3.8.4)
**Was:** After the item-5 fix, `log_bug` no longer crashed on Cloud Run — but it could only write to the read-only repo root (fail) then an ephemeral temp file, so bugs logged from the *deployed* HAL never persisted (lost on restart, never reached the repo). That's why HAL kept saying entries were "provisional (temp file only)."
**Fix:** `backend/mcp_server.py` now persists bugs to a durable, GCS-synced store `backend/hal_bugs.json` (inside the writable app dir, added to `core/gcs_sync.py::_SYNC_FILES` like `review_queue.json`), and still mirrors the human-readable entry into the repo `MFIBugs.md` when that's writable (local checkout). Added a `list_bugs` MCP tool to read the store back. Root cause of the silent read-empty: `json` was never imported in `mcp_server.py`, so `_load_bug_store`'s `json.loads` raised a swallowed `NameError` — fixed. Now durable on Cloud Run (same bucket path the app already uploads `review_queue.json` to).

### 7. CMS Medicare FFS Utilization API returns 410 Gone — FIXED (higher priority)
**Was:** `services/medicare_lookup.py` called the retired CMS Socrata endpoint `data.cms.gov/resource/fs4p-t5eq.json`, which now returns HTTP 410. The Medicare Cross-Reference / discrepancy check was blind for ALL providers, not just Dunlap.
**Fix:** Migrated to the current CMS data-api: `data.cms.gov/data-api/v1/dataset/92396110-2aed-4d63-a6a2-5d6207d46a29/data` (2024 release), with `filter[Rndrng_NPI]=`/`size=` paging and PascalCase column names (`Rndrng_NPI`, `HCPCS_Cd`, `Avg_Sbmtd_Chrg`, `Avg_Mdcr_Pymt_Amt`, `Tot_Srvcs`, `Tot_Benes`, `Rndrng_Prvdr_Type`, `HCPCS_Desc`). Verified live: real data returns; non-Medicare providers return `has_data:false` with no error. To bump to a future annual release, pull `data.cms.gov/data.json` and update the UUID.

## 2026-07-09 — JARVIS backlog batch (v3.9.0)

Handoff spec of 6 items reviewed and actioned.

**#3 Data-freshness "as of" badge on exclusion checks — FIXED.** New user-accessible `GET /api/providers/exclusion-freshness` returns LEIE (record count + cache mtime), SAM (last-success + data-as-of), and NPPES (live) freshness; `core/oig_store.get_oig_stats` now includes `last_updated_utc`. `ProviderDetail` renders an `ExclusionFreshnessBadge` strip under the exclusion banners. Verified: LEIE 2026-06-18, SAM live date, NPPES "live".

**#4 Cluster-level risk scoring for provider networks — FIXED.** `services/ownership_tracer.py` and the `/{npi}/ownership-chain` endpoint (the UI's source) now return `cluster_risk_score` + `cluster_risk_band` — worst-actor-weighted (0.6·max + 0.4·mean) plus a size escalation (+4/entity, cap 30) for the shell pattern, capped at 100. Also returned by the MCP `provider_network` tool. `OwnershipTracePage` shows a "Cluster Risk" KPI card.

**#5 Peer-group definition transparency — FIXED.** `provider_signal_evidence` now attaches `peer_group_definition` (basis = same primary HCPCS code, peer_count, mean/std, geography=national, size_band=none, plus an explicit specialty-mismatch caveat) alongside the existing threshold/proof numbers. Named separately from the legacy `peer_group` string label to avoid collision.

**#6 Stale-case alert for review queue — FIXED.** `core/review_store` adds `is_stale_case`/`case_stale_days`/`get_stale_cases` (active cases — open/under_review — untouched >14d by `queue_status_updated_at`); `/api/review` enriches list items with `stale`/`stale_days`, adds `GET /api/review/stale`, and counts.stale. `ReviewQueue` rows show a "STALE Nd" badge.

**#2 Brain-flag parity — FIXED (v3.9.1).** Three changes, per Dave's go-ahead: (a) Brain-membership badge map widened from top-100 to top-500 (the backend cap) in `useProviderFlags`, so the BRAIN# chip actually appears for board providers surfaced on Claim Patterns / Billing Codes; (b) `routes/claim_patterns.py` now stamps each pattern row with the provider's composite `risk_score` (cache lookup), and `ClaimPatterns.tsx` renders a red `RISK n` chip at the shared threatBand threshold (HIGH ≥60) next to the NPI in all five tables; (c) `BillingCodeSearch`'s RiskBadge red threshold aligned from ≥70 to ≥60 so "high risk" means the same score on every page. Verified: all pattern rows carry risk_score; chip fires only at ≥60.

### 10. STALE badge clipped mid-render in Review Queue — FIXED (v3.9.3)
**Was:** Reported by Dave from a screenshot: the provider-name cell truncates with `overflow:hidden` (`max-w-[180px] truncate`), and the STALE badge (added in the #6 fix) lived inside that same truncated container. For a long provider name (e.g. "HOMEBRIDGE INC"), the name's ellipsis-clip sliced straight through the badge — leaving only a dark curved fragment of its border visible, no legible text. Looked like a broken/blocked UI element.
**Fix:** `ReviewQueue.tsx` — only the name text truncates now (wrapped in its own `truncate min-w-0` span); `ProviderFlags` and the STALE badge sit outside it with `shrink-0`, so they always render in full regardless of name length. Verified live: reproduced the exact clipped state on NPI `1790954691` (HOMEBRIDGE INC, CA), confirmed the fix renders the full "STALE 50d" badge (67px, unclipped) after the change.

### Claim-level data ingestion pipeline
- **Logged:** 2026-07-09 16:08 UTC (via HAL)
- **Severity:** medium
- **Area:** Fraud Brain / data
- **Detail:** Brain reasons only over provider-summary and HCPCS-summary aggregates; no raw claim-line data exists in MFI. Build a pipeline to ingest claim-level detail to enable finer patterns (unbundling, duplicate billing, line-item upcoding). Large roadmap item - requires a claim-line data source MFI does not currently have. Not buildable without a source extract.
- **Status:** **WONTFIX (2026-07-26)** — closed as permanently blocked, not deferred.

  **Why this is not a roadmap item.** MFI is built entirely on public, DUA-free data
  (see `/methods`). Claim-line detail is not withheld from MFI by effort or priority —
  it does not exist in any dataset MFI can lawfully obtain:

  * **HHS Medicaid Provider Spending** (the payment backbone, 227M rows) is published
    pre-aggregated to `billing NPI × HCPCS × month`. There is no line detail, no
    modifier field, no ordering/referring NPI, no service date, no beneficiary key.
    Unbundling, duplicate-line billing and line-item upcoding are all *within-claim*
    patterns — the grain needed to see them was collapsed before publication.
  * **T-MSIS/TAF RIF via ResDAC** does carry line detail, and is the only real source.
    It requires an IRB approval, a HIPAA waiver, an organizational signatory and
    five-figure fees. It is not obtainable by an individual, at any price.
  * **Verified dead ends** (researched 2026-06-13, do not re-propose): SDUD is
    state × NDC × quarter with no NPI; state "checkbook" portals exclude Medicaid
    provider payments by statute (SSA 1902(a)(7), 42 CFR Part 431); APCDs cover about
    half the states and are DUA/fee-gated.

  **Consequence, stated plainly:** unbundling, duplicate billing and line-item
  upcoding are permanently out of scope for MFI. The app detects *provider-level*
  patterns — concentration, ramp, ghost billing, bust-out, per-se exclusion — and
  should not imply otherwise in narratives or marketing.

  Reopen only if a genuinely public, line-level Medicaid extract is released. Acquiring
  restricted data would forfeit the property that makes every MFI referral verifiable by
  the recipient against the same public files.

### Brain flag / high-risk parity on Claim Patterns + Billing Codes
- **Logged:** 2026-07-09 16:08 UTC (via HAL)
- **Severity:** medium
- **Area:** Claim Patterns / Billing Codes
- **Detail:** Requested: add the BRAIN# flag + a high-risk alert rule for consistency with Beneficiary Fraud / Pharmacy. Finding: ProviderFlags (BRAIN# chip) is ALREADY rendered on all four pages; ClaimPatterns shows SeverityBadge and BillingCodeSearch shows RiskBadge. The chip is membership-conditional (Brain top-100), so it rarely appears for these pages providers. Resolved by widening membership to top-500 + composite-risk chip on Claim Patterns + shared >= 60 threshold (see v3.9.1 entry above).
- **Status:** FIXED (v3.9.1)
