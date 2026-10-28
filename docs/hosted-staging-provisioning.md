# Hosted staging provisioning evidence — 2026-10-27

Subsequent update: the production public-read finding described below was repaired under explicit approval. Operational storage now enforces public-access prevention and has no anonymous IAM grants; both services use a separate public dataset-only bucket. See [completed production repair](production-privacy-repair-results.md). Earlier finding/permission statements below record the pre-repair investigation.

Authorized shared-project scope: staging resources only inside `medicaid-inspector`. No production resource, project-wide IAM or Firebase Hosting configuration was changed.

## Created and reconciled

| Resource | Verified state |
| --- | --- |
| Bucket `gs://medicaid-inspector-staging-validation` | US-CENTRAL1; uniform bucket-level access enabled; public access prevention enforced |
| Runtime identity `mfi-runtime-staging@medicaid-inspector.iam.gserviceaccount.com` | Dedicated staging service account created |
| Secret reference `mfi-staging-admin-password:1` | Exactly one enabled version; generated in memory and piped directly into Secret Manager; value not printed or saved locally |
| Bucket-specific grant | New runtime identity has `roles/storage.objectAdmin` only on the staging bucket |
| Secret-specific grant | New runtime identity has `roles/secretmanager.secretAccessor` only on the staging secret |

CLI metadata confirms billing enabled and Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Storage and IAM APIs enabled. Active provisioning actor has Owner permission; no new project-wide role was granted. The initial exact resource names were absent before creation. A reconciliation after interruption confirmed the first secret version and both grants already existed, so they were not duplicated.

The staging bucket currently inherits ordinary project owner/editor/viewer legacy bucket roles. The new staging runtime identity has no direct project role and no project-level blanket `allUsers`, `allAuthenticatedUsers`, or all-ServiceAccount principal-set binding was found. Shared-project isolation therefore remains resource-scoped rather than organizational/project isolation. Organization-level deny policies and indirect group memberships were not independently audited.

Default soft deletion is enabled for seven days. Deleted objects may remain billable during that retention window; do not describe eventual cleanup as immediate data erasure or zero remaining storage charges.

## Existing production public-read finding (metadata only)

The authoritative IAM policy for `gs://medicaid-inspector-data` includes `allUsers` with `roles/storage.objectViewer`. This is bucket-scoped public object read/list access, not limited by this policy to the public raw dataset. No production objects were listed or read during this investigation, so actual content exposure has not been enumerated.

Both listed existing Cloud Run services (`medicaid-inspector`, `medicaid-inspector-api`) run as `447172598773-compute@developer.gserviceaccount.com`. That identity has project `roles/editor` and an explicit production-bucket `roles/storage.objectAdmin` grant. Authenticated Google Storage SDK reads/writes should therefore retain IAM permission if the public viewer grant is removed. This is an IAM-based assessment; object-access behavior was not tested against production.

Removing the public grant alone can still break a different path: the application currently reads raw Parquet using an anonymous HTTPS Storage URL through DuckDB. Those requests do not automatically inherit the Python Storage SDK identity. They would be expected to receive 403 after the bucket becomes private unless the dataset is moved to an intentionally public data-only bucket or the raw reader is explicitly authenticated. Preserve manifests/source identity and data provenance if changing that source.

The staging identity is also able to read public production objects through this pre-existing anonymous grant, despite receiving no production role. Strict production-read isolation cannot be claimed while that public grant exists. Production permission changes require separate user approval and a compatible raw-data access plan; none were made here.

## Hand-off

Root coordinates image build, private `mfi-api-staging` deployment and runtime verification. This subtask did not build/deploy a service, alter live Hosting, read production data or submit referrals. The staging admin password is available only through its Secret Manager reference to authorized actors; retrieve it into memory for a test request, never echo it.

## Staging verifier impersonation grant

For runtime-identity CAS verification, the active verifier received `roles/iam.serviceAccountTokenCreator` only on the fresh `mfi-runtime-staging` service-account resource. No project-wide binding was added. The resource policy was read back and confirms the active actor's matching grant. Immediate token checks returned permission denied during propagation. A later memory-only check successfully obtained a Storage-scoped token for the staging identity. This confirms impersonation availability; bucket/CAS behavior still requires its separate runtime verification.

The local helper `backend/scripts/staging_identity_token.py` captures gcloud token output in memory and returns a Storage-scoped token to an in-process caller; its command-line mode prints availability only. Never print or persist its return value. Remove the temporary verifier grant under cleanup authorization after verification if no further impersonation is needed.

Completed cleanup: root removed the temporary verifier Token Creator binding after the real CAS check and verified that the actor no longer has that binding on the staging account. The grant described above is historical, not current permission. No project or production IAM was changed. See [completed hosted verification](hosted-staging-results.md).
