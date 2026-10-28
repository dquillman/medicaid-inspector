# Isolated hosted staging — setup history

Current state: private shared-project staging is deployed and verified with synthetic data. See [hosted results](hosted-staging-results.md) and [provisioning evidence](hosted-staging-provisioning.md). Production privacy repair was separately approved and completed; see [verified repair](production-privacy-repair-results.md). The preparation/approval notes below are historical.

Verified 2026-10-27 using read-only CLI metadata, without calling the live application:

- Active gcloud project: `medicaid-inspector`; signed-in credentials usable outside the filesystem sandbox.
- Related accessible project search returned only `medicaid-inspector`.
- Firebase site: `medicaid-inspector`; only the `live` hosting channel exists.
- Cloud Run: only `medicaid-inspector-api` listed in that project.
- Buckets: production data, Cloud Build, and Run source buckets; no staging data bucket found.
- Sandbox Firebase auth errors were misleading: the same metadata commands succeeded with filesystem access to CLI configuration. Reauthentication is not currently the blocker.
- Application login uses `backend/core/auth_store.py`, `users.json`, `sessions.json`, and `ADMIN_PASSWORD`. Firebase Hosting sign-in is deployment access, not application authentication.

## Current blocker

No isolated hosted target exists in the accessible project inventory. Provisioning a private staging bucket, runtime service account, staging secret and Cloud Run service, and building/deploying are external/billable changes. They have not been performed. A separate project remains the default plan; explicit shared-project mode can reuse the existing project/billing while isolating staging resources. User approval for that shared-project resource scope is pending. Existing live hosting must not be used as a staging workaround. A Firebase preview channel using the current repository firebase.json would still rewrite API traffic to the production Cloud Run service.

## Configuration prepared locally

Run the non-network generator from the repository root, using actual approved staging names:

```powershell
& G:\Python311\python.exe backend/scripts/prepare_hosted_staging.py --project YOUR-staging-project --bucket YOUR-staging-data --output backend/.tmp/hosted-staging-config
```

It rejects production services/buckets, requires staging resource names, refuses overwrites, and emits isolated Firebase config, explicit environment settings, and a deployment plan. A production project ID is rejected unless shared-project mode is explicit. It does not create projects, link billing, build, upload, deploy, or read secrets.

## Explicit shared-project alternative (approval pending)

```powershell
& G:\Python311\python.exe backend/scripts/prepare_hosted_staging.py --shared-project --project medicaid-inspector --service mfi-api-staging --bucket YOUR-staging-data --output backend/.tmp/hosted-shared-staging-config
```

This prepares a new staging-named Cloud Run service and private bucket inside the existing `medicaid-inspector` project. It does not authorize or perform provisioning. The fresh runtime identity is `mfi-runtime-staging@medicaid-inspector.iam.gserviceaccount.com` and the fresh secret reference is `mfi-staging-admin-password:latest`; do not reuse the production service account or production admin secret. Verify that these names are absent before creating them; if already present, inspect ownership and choose new staging-only names before proceeding. The generator does not inspect IAM or guarantee that a named service account is actually fresh.

The shared-project generated `firebase.json` deliberately contains an empty Hosting list. Do not run Firebase deployment at all in this mode. Do not alter the live site, its rewrite, production service, production bucket, production secrets or project-wide IAM. Grant runtime permissions only on the staging bucket and staging secret; audit inherited project roles because a dedicated account in the production project is insufficient isolation if it inherits broad project permissions.

Use private Cloud Run IAM invocation and a developer proxy for authenticated API smoke tests. Hosting/browser same-origin integration remains unverified unless separately authorized using a dedicated staging site. Local browser staging may point only at the authenticated developer proxy with appropriate local CORS settings. The pending approval for service/bucket does not implicitly authorize a new Firebase site or opening a public backend.

Use the deployment sequence below with these substitutions: skip new project/billing/Firebase creation; explicitly pass `--project medicaid-inspector` with only the staging service name, staging account, staging env and staging secret; never call the existing production deploy scripts. No project-wide IAM grants. For cleanup remove only the specifically created staging resources after verification; never delete the shared project.

## Concrete separate-project provisioning and deployment sequence (pending authorization)

1. Create or nominate a dedicated Firebase/GCP staging project and confirm billing. Keep it separate from `medicaid-inspector`. Enable the APIs needed for Cloud Run, Cloud Build, Artifact Registry, Storage and Secret Manager. Register Firebase Hosting in that project.
2. Create a private, uniform-access staging bucket in `us-central1`. Block public access. Create a dedicated runtime service account with object access only to that bucket and Secret Accessor only for the staging admin secret. Do not grant any production bucket/secret role; inspect inherited cross-project IAM before using it.
3. Create a fresh staging-only admin secret through Secret Manager. Do not print its value or put it in generated YAML, command history, a source file, or a frontend variable. Never copy production users, sessions, app.db, cases, referrals, evidence or logs into staging.
4. Build from a NEW source-only directory. Copy backend Python source and requirements plus required frontend source/assets and Dockerfile. Exclude all operator JSON/DB/Parquet/logs, `.env`, `.tmp`, credentials and secrets. The current `.dockerignore` and `.gcloudignore` have been hardened to exclude backend operational JSON except the two public startup reference stores, `.tmp`, datasets, credentials and private evaluation material. A fresh source-only build remains preferred because explicit allowlisting is easier to audit than relying solely on ignore patterns. Verify that the reviewed exclusions apply to the actual build context.
5. Seed only synthetic fixtures or explicitly approved public aggregate data/derived indexes. Put a valid local Parquet fixture at `/app/data/medicaid-provider-spending.parquet`; the current loader requires size over 1 MB and PAR1 header. Otherwise it falls back to the staging-only URL, whose private bucket should return denied rather than reaching production. A private bucket HTTP URL is not an authenticated DuckDB source: local fixture packaging is required for raw-data drilldown in this plan. Run full-source scans locally, not inside the 4 GiB hosted test instance.
6. Build a staging image in the staging project. Review its contents before deployment; deployment parameters must use the generated project, service, service account, env file and secret reference. Set request-based billing, min instances 0, max instances 1, CPU 1, memory 4 GiB, concurrency 4 and timeout 300 s. The JSON/SQLite state model still requires one instance.
7. For browser testing, Firebase Hosting rewrites require the backend invocation path to be accessible. The staging app still enforces its separate app login. If public invocation is unacceptable, use a private Cloud Run service through authenticated developer proxy for API tests instead; do not claim ordinary browser Hosting access works through that private IAM gate.
8. Build the frontend with `/api` as API base in the clean directory. Deploy Hosting only with generated isolated config and an explicit staging project argument. Do not reuse the existing deploy-backend.sh or cloudbuild.yaml, which select production service/secrets.
9. Use a fresh staging app login and test role permissions, evidence upload, packet generation, recovery, sign-out and expired sessions. Record source commit/build version, role/action/status, redacted screenshots and artifact hashes. Confirm new objects exist only in the staging bucket. The disabled-background environment prevents scheduled fetch/auto-prep, not every on-demand external free-data request; avoid external-enrichment routes unless separately allowed. Paid/LLM/HAL/SMTP keys are blank.
10. Capture the final verification report, remove disposable hosting channels/service/images and staging data under explicit cleanup authorization, and verify no billing resources remain. Do not delete production resources. Project deletion is irreversible and is not automated here.

## Cost envelope and limits

No spending occurred in this preparation. Billing permission and a cost ceiling are still needed before provisioning. Min instances 0 and max instances 1 limit exposure but are not a spending cap; budget alerts do not stop usage.

At the published us-central1 request-based list prices, 1 vCPU + 4 GiB for one fully active hour is approximately `3600 × (0.000024 + 4 × 0.0000025) = $0.1224`, before free tier and excluding requests, builds, images, logging, secret operations and egress. Free tier is shared across the billing account, not guaranteed available to this project. See [Cloud Run pricing](https://cloud.google.com/run/pricing).

Standard regional Storage is about $0.02/GiB-month at current published rates; operations and transfer are separate. Keep snapshots minimal and colocated. See [Storage pricing](https://cloud.google.com/storage/pricing). Hosting/Blaze also involves separate Cloud Build, Artifact Registry, logging and secrets usage; [Firebase pricing](https://firebase.google.com/pricing) links those components. Treat the compute figure as one component, not an all-in estimate.

## Credential-output caution

`firebase login:list --json` includes token fields and must not be used for a report. Use metadata-only commands without raw authentication JSON, or parse/filter securely before any output. No token values are stored in this document or configuration generator.
