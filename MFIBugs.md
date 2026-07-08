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
