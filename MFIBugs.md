# MFI Bug Log

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

### Claim-level data ingestion pipeline
- **Logged:** 2026-07-09 16:08 UTC (via HAL)
- **Severity:** medium
- **Area:** Fraud Brain / data
- **Detail:** Brain reasons only over provider-summary and HCPCS-summary aggregates; no raw claim-line data exists in MFI. Build a pipeline to ingest claim-level detail to enable finer patterns (unbundling, duplicate billing, line-item upcoding). Large roadmap item - requires a claim-line data source MFI does not currently have.
- **Status:** OPEN

### Brain flag / high-risk parity on Claim Patterns + Billing Codes
- **Logged:** 2026-07-09 16:08 UTC (via HAL)
- **Severity:** medium
- **Area:** Claim Patterns / Billing Codes
- **Detail:** Requested: add the BRAIN# flag + a high-risk alert rule for consistency with Beneficiary Fraud / Pharmacy. Finding: ProviderFlags (BRAIN# chip) is ALREADY rendered on all four pages; ClaimPatterns shows SeverityBadge and BillingCodeSearch shows RiskBadge. The chip is membership-conditional (Brain top-100), so it rarely appears for these pages providers. Real options: widen Brain membership coverage or add an explicit cross-signal high-risk row highlight. Needs Dave to confirm intended behavior before building on the (inaccurate) missing-flag premise.
- **Status:** OPEN
