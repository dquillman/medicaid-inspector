# Medicaid Inspector — Security & Compliance Posture

> **Audience:** MCO Information Security reviewer, state agency security officer, vendor risk team
> **Purpose:** Single-page reference for security review during pilot scoping
> **Last updated:** 2026-05-28 · **Owner:** Dave Quillman, Medicaid Inspector
>
> Designed to fit on one printed page (US Letter, 10pt) when rendered. We do not overclaim. Items in **bold** are current production state; items marked *(roadmap)* are committed but not yet shipped.

---

## Glossary (first-mention expansions)

MCO (Managed Care Organization) · SIU (Special Investigations Unit) · PI (Program Integrity unit, state-side) · MFCU (Medicaid Fraud Control Unit, state AG investigative arm) · BAA (Business Associate Agreement) · MSA (Master Services Agreement) · MLR (Medical Loss Ratio) · T-MSIS (Transformed Medicaid Statistical Information System) · PERM (Payment Error Rate Measurement program) · MMIS (Medicaid Management Information System) · PHI (Protected Health Information) · RBAC (Role-Based Access Control) · SIG Lite / AHA VSRA (industry vendor-risk questionnaires) · IaC (Infrastructure as Code).

## Public methods note

Methodology, data provenance (including Medicare-skewed CMS reference data limitations), cohort definitions, signal thresholds, and known limitations are published publicly at `medicaid-inspector.web.app/methods` (or linked from the GitHub README). Security reviewers and data teams are encouraged to read this alongside this document.

## Architecture (security-relevant)

- **Stateless backend.** FastAPI service queries claims data directly from your designated storage (DuckDB-over-Parquet, read-only). Claims data is loaded into memory only for the duration of a request; no PHI is written to local disk or persistent storage on MFI infrastructure. Standard Python garbage collection applies; we do not claim secure-erase of in-memory PHI between requests.
- **Read-only data access.** No write paths back into your claims store. Outputs (ranked queues, evidence dossiers) are written only to MFI's own service tier, never to your source data.
- **Container isolation.** Backend runs on **Google Cloud Run** (us-central1), auto-scaled 0–3 instances, 2 GB memory cap, ephemeral filesystem. No persistent volumes. No shell access in production.
- **Frontend isolation.** React SPA served from **Firebase Hosting**. API calls proxied through Firebase rewrites to the Cloud Run service. No direct backend exposure.

## Authentication & access control

- **Role-based access control (RBAC).** Three roles: `admin`, `analyst`, `user`. Permissions enforced at the route level in FastAPI. Role changes audit-logged.
- **Session management.** Session tokens, server-side validation, rate limiting on login attempts.
- **Admin account recovery.** Out-of-band `reset-admin-password.sh` for support; bootstrap admin password managed via `ADMIN_PASSWORD` env var, never committed to source.
- **Federated identity** *(roadmap, in progress as of 2026-05).* Google Sign-In via OAuth 2.0 ID token verification (backend verifies against Google's certs; passwordless on the MFI side). Pluggable for SAML/SSO if a customer requires it for production.

## Data handling

- **No PHI at rest in MFI infrastructure.** Claims data resides in customer-controlled storage (Azure Blob Storage today; customer-controlled GCS/S3/SFTP supported for pilots). MFI queries via signed read-only URLs or service-account-scoped access.
- **HIPAA-aware audit logging.** Every PHI access — every query, every dossier export, every report download — is recorded in `phi_access_log.json` with user, timestamp, resource accessed, and request context. Retained per customer policy (default 7 years).
- **Configurable rule engine.** `alert_rules.json` and `watchlist.json` are editable without redeploy. All rule changes audit-logged.
- **Data discovery & validation.** `data_validator.py` enforces schema constraints on ingested claims; `data_discovery.py` profiles incoming extracts for quality issues (missing NPIs, duplicate claim IDs, date-range gaps).
- **Pilot data deletion.** On pilot conclusion (whether extended or ended), all derived artifacts (ranked queues, dossiers, model state, audit-log copies) are destroyed within 30 days unless customer requests retention in writing.

## Transport & network security

- **TLS everywhere.** HTTPS-only at Firebase Hosting and Cloud Run. HSTS enabled at the edge.
- **Production security headers.** Verified deployed:
  - `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy` strips camera, microphone, geolocation, payment APIs
- **No public backend ports.** Cloud Run service is invoked only via the Firebase Hosting rewrite; no direct ingress.

## Source code & supply chain

- **Closed contributor model** — all commits authored by Medicaid Inspector personnel with full provenance; no anonymous or unverified contributors. **Business continuity:** source code in version-controlled remote repo (GitHub); infrastructure-as-code reproducible from `Dockerfile`; customer claims data remains in customer storage so vendor disappearance does not strand the customer; source-code escrow available on request for production contracts, triggered by founder incapacitation or business cessation.
- **Dependency monitoring:** GitHub Dependabot alerts reviewed on every push. As of this writing, **0 critical / 0 high outstanding** ([open: 3 moderate/low, tracked]).
- **Python:** 3.11; FastAPI, DuckDB, scikit-learn, google-auth, anthropic. **TypeScript:** React, Vite, Tailwind, TanStack Query.
- **CI/CD:** Google Cloud Build pipeline; backend builds reproducible from `Dockerfile`; frontend builds reproducible from `vite.config.ts`.

## Certifications & attestations — honest stance

We do not claim certifications we don't hold. Our current posture:

| Standard | Status |
|---|---|
| **HIPAA technical safeguards** (45 CFR § 164.312) | Implemented: access controls, audit controls, integrity controls, transmission security. Full BAA willing — we'll sign yours. |
| **SOC 2 Type II** | Not certified today. Bridge mechanisms offered: (a) HITRUST-aligned self-assessment via AHA Vendor Security Risk Assessment v6, (b) contractual security representations matching SOC 2 CC controls with right-to-audit clause, (c) cybersecurity insurance certificate ($X aggregate), (d) customer-funded Type I audit completable in 90 days. Type II initiated within 30 days of first production contract. |
| **HITRUST CSF** | Not certified. Considered for 2027 H1 if customer demand requires. |
| **FedRAMP Moderate** | Not pursued. Would require federal agency sponsorship. |
| **State-specific (e.g., TX-RAMP, CA-Hosted)** | Not pursued. Will pursue per customer requirement. |
| **NIST 800-53 / NIST 800-66 alignment** | Aligned but not third-party audited. Self-assessment available on request. |

If your procurement process requires a third-party attestation that we don't currently hold, we'll discuss whether a customer-funded audit or a contractual representation can bridge the gap during the pilot, with the certification on the production-contract roadmap.

## Incident response

- **Primary security contact:** security@medicaid-inspector.web.app (monitored by Dave Quillman + designated backup [name fractional CISO or contracted ISO consultant]). After-hours: monitored alerts route via PagerDuty; 24/7 acknowledgement SLA; response SLA 4 hours business / 8 hours non-business. Solo-founder shop — disclosed honestly; succession contact and source-code escrow available on request.
- **Notification commitment:** any security event affecting customer data communicated within 24 hours of detection, with preliminary root-cause within 72 hours, full post-mortem within 30 days.
- **Backups:** `backup.py` runs scheduled snapshots of MFI-owned state (configuration, audit logs, queue state) to Google Cloud Storage with versioning enabled. Customer claims data is *not* backed up by MFI (it remains in customer storage).

## Business associate agreement

We will sign your BAA. We have a template available if you prefer to start from one — covers permitted uses, safeguards, subcontractor restrictions, breach notification, and termination requirements per 45 CFR § 164.504(e).

## Subcontractors / sub-processors

| Vendor | Purpose | Data accessed |
|---|---|---|
| Google Cloud (Cloud Run, Cloud Storage, Cloud Build) | Compute, deployment, MFI-state storage | MFI-owned state only — no customer PHI |
| Firebase (Hosting) | Frontend delivery | None |
| Anthropic | LLM-generated case-narrative drafts | Disabled by default in pilot configuration. Opt-in only with: (1) executed Anthropic Enterprise/BAA-tier agreement, (2) verified zero-retention configuration, (3) tokenization of provider names and NPIs before egress (no raw PHI or PHI-adjacent identifiers sent), (4) written customer approval per pilot. All summaries audit-logged. |
| Google Identity (Sign-In) | Optional federated auth | Authenticated user email only |

No customer claims data is sent to any subcontractor in default configuration.

## Contact

**Dave Quillman** — Founder, Medicaid Inspector
dquillman2112@gmail.com · medicaid-inspector.web.app
*Available for security-review calls within 48 hours of request.*
