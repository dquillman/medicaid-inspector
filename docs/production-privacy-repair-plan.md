# Production bucket privacy repair — approved execution plan

Current status: approved by the user and completed. See [verified results](production-privacy-repair-results.md). The notes below retain the original pre-execution inventory and sequence. Controlled sequential cutovers were used; the older service additionally required a memory increase after verified startup exhaustion. The private bucket now has public-access prevention enforced and no anonymous grants.

The read-only original IAM backup is also retained durably under `backend/private_validations/20261027-hosted/production-bucket-policy.before.json`, covered by that directory's SHA256 retention inventory. The earlier `.tmp` copy remains available for the commands below. Production repair has not been executed.

Read-only preflight completed 2026-10-27. No bucket/object copy, production service change or production IAM mutation has been performed by this task. The plan has three distinct changes requiring the coordinating agent's approval checkpoint: public aggregate-only bucket/copy, both services' dataset URL updates, then production state bucket public-viewer removal.

## Verified inventory

- Existing state/data bucket: `gs://medicaid-inspector-data`; authoritative policy contains `allUsers` with `roles/storage.objectViewer` at bucket scope.
- Candidate public-data-only bucket: `gs://medicaid-inspector-public-aggregates`; metadata describe returned 404. The name has not been reserved; recheck before creation.
- Copy exactly `medicaid-provider-spending.parquet`, source generation `1774579251010800`, size `2940234191` bytes, CRC32C `KFYNRQ==`, STANDARD class. This is the documented public provider aggregate dataset, not operational JSON, app.db, evidence or referral state. Object metadata was read; contents were not downloaded or inspected during this preflight.
- Private policy backup: `backend/.tmp/privacy-repair-20261027/production-bucket-policy.before.json`; SHA-256 `837d65a1bcc3a2afe989c12dc2089a74f0a3797963e4d481c66c3bd669a39982`; policy etag at capture `CAM=`. It contains IAM metadata only and is excluded from source/build context.

| Existing service | Current serving revision | Traffic | Immutable serving image |
| --- | --- | --- | --- |
| `medicaid-inspector-api` | `medicaid-inspector-api-00189-9pw` | 100% | `us-central1-docker.pkg.dev/medicaid-inspector/cloud-run-source-deploy/medicaid-inspector-api@sha256:09e1749c9888dd097027fee77997e095449665111dd95b1ca598c0e8efa56806` |
| `medicaid-inspector` | `medicaid-inspector-00004-ng7` | 100% | `gcr.io/medicaid-inspector/backend@sha256:3c7905cfa2df9d19479ff3e00dbd1fe9a26be816c001b7ef55cb197a88b4530f` |

`PARQUET_URL` is absent from both active service environment lists. Repository settings default to the state bucket's public HTTPS object. The older service's configured image is a mutable tag; its immutable serving digest above was resolved from revision metadata. Pin that exact digest when making a URL-only revision so a moving tag cannot introduce unrelated code.

Both services use `447172598773-compute@developer.gserviceaccount.com`. The runtime account has project Editor and an explicit state-bucket `roles/storage.objectAdmin` grant. Authenticated Storage SDK access should retain read/write permission after removal of `allUsers`; this is verified IAM evidence, not a production object-access test. Anonymous DuckDB reads of the old HTTPS URL will cease to work after revocation, hence the required URL migration first. Do not assume the older service is unused simply because current Firebase rewrites point to the API-named service.

## Ordered execution after approval

1. Re-read policy etag and both service traffic/image metadata. Stop if they changed; reconcile other releases instead of replaying stale configuration. Verify the private backup hash. Confirm bucket creation approval/cost scope.
2. Create only the candidate data-only bucket in `us-central1`, STANDARD, uniform bucket-level access. The bucket must permit intentional public access; do not alter project-wide public-access policy to force it. If organization policy forbids public buckets, stop and implement authenticated raw-data access instead.
3. Copy only the pinned source object generation to the same filename in the new bucket. Use a source generation-qualified URI and destination `if-generation-match=0` so a race cannot overwrite unrelated data. Do not recurse, sync buckets, copy ACLs, or include any other state objects. Server-side copy still incurs storage/operation costs.
4. Verify destination size and CRC32C exactly match the pinned source metadata. Check that the destination bucket contains exactly that one allowlisted object. Grant `allUsers` objectViewer only on this data-only bucket. It must never become the app's `GCS_BUCKET` or receive operational sync output.
5. Verify the new raw dataset URL anonymously using bounded public-data checks: HTTP metadata/range support and a limited Parquet metadata/query check, not a full download. Expected URL: `https://storage.googleapis.com/medicaid-inspector-public-aggregates/medicaid-provider-spending.parquet`.
6. Create dataset-URL-only revisions for BOTH existing services, pinning their immutable current images and preserving all other environment values, secrets, runtime identity and sizing. Use `--update-env-vars PARQUET_URL=...`, not `--set-env-vars`, to preserve existing settings. Prefer no-traffic revisions for initial checks. A no-traffic tagged revision may still initialize and write shared operational state; it is NOT isolated staging. Do not run mutating tests or allow duplicate background work. Consider a controlled one-service-at-a-time cutover instead if the existing startup/background behavior cannot be safely paused.
7. Validate public dataset reads on each updated service and verify SDK bucket access through the existing IAM grants. Use authorized read-only endpoints; do not mutate cases or exercise tip submissions. Capture redacted health/source-query evidence and exact new revisions. Route traffic deliberately and verify each service's effective `PARQUET_URL` metadata. Retain old revisions for configuration evidence, not as an assumed safe post-revocation fallback.
8. Confirm precomputed artifact provenance behavior before revocation: the source URL changes although bytes remain identical. Do not label stale artifacts current or silently disable investigations because manifests still name the old URL. Rebuild/validate compatible derived artifacts when required by the deployed version. Confirm ordinary future deploy scripts preserve the new URL; an existing `--set-env-vars` deployment can otherwise remove the override and regress to the private default.
9. Recheck state-bucket IAM etag; remove ONLY `allUsers` from the `roles/storage.objectViewer` binding using a conditional/read-modify-write operation. Preserve every other member and role. Do not replace the entire old policy without concurrency protection. No project-wide IAM changes.
10. Verify the authoritative state-bucket policy no longer includes public/all-authenticated grants, and anonymously HEAD a known-existing private-state object chosen from metadata only: expect denied with no contents returned. Verify the public dataset object remains readable in the new bucket and both service raw queries still work. Verify runtime SDK initialization/state reads and persistence health without changing a real case. Record the completed IAM fingerprint and service revisions privately.

## Rollback and stop conditions

- Before state-bucket revocation: an unsuccessful URL revision may be routed back to its exact previous revision while the old raw URL is still public. Preserve the newly copied public dataset and logs; do not delete resources reflexively.
- After revocation: routing back to old revisions would normally restore their old now-private anonymous dataset URL. Prefer correcting the dataset URL on the same known image, or authenticated access, without reopening operational data.
- Restoring the public `allUsers` grant is a last-resort confidentiality regression and requires explicit additional user approval. Do not automatically restore the saved policy or public access to repair a raw-data outage. If approved, restore only the specific binding with an up-to-date etag and document the exposure window.
- Do not delete the original raw object or retire the older service as part of this repair; neither action is needed or approved here.

## Costs and residual verification limits

The data-only bucket adds approximately 2.74 GiB of storage plus operations; same-region copy avoids ordinary cross-region transfer, but actual billing/free-tier coverage must be checked. Service URL changes create revisions and can incur startup/request compute. This document is a concrete plan, not a spending cap or a claim that repair has already occurred.

No production object contents were read for this plan. Existing public-object exposure was inferred from authoritative IAM, not enumerated or exploited. Current application behavior has not been tested against production endpoints in this read-only planning task.
