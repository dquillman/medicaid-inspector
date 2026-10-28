# Hosted staging verification runbook

Status: harness and synthetic tests prepared. No hosted resources have been
contacted by this preparation. Root/operator must approve the exact resources
and provide their references before execution. Production deployment, requests,
provider data, production bucket objects and agency contact are outside scope.

## Approve and isolate

Create a private resources JSON containing approved_staging_only=true,
project_id, service_name, bucket and service_url. Service and bucket names must
contain a separate stage/staging component. The URL must be the exact approved
HTTPS Cloud Run service hostname; production defaults are refused. Optional
proxy_url must be an explicit `http://127.0.0.1:PORT` set up by the operator with
`gcloud run services proxy APPROVED_STAGING_SERVICE --project APPROVED_PROJECT
--region APPROVED_REGION --port PORT`. Record that command's service target in
private evidence. The harness never starts a proxy or deploys/restarts a service.
Redirects are refused. A valid staging URL does not independently prove a proxy
points at it: verify the operator's proxy process/command metadata.

Run plan mode first (no network requests or writes):

```
G:/Python311/python.exe backend/scripts/verify_hosted_stage.py PRIVATE_RESOURCES.json
```

Use a dedicated staging runtime service account and a separate verification
identity. The runtime identity needs only its dedicated staging bucket; the
verification identity needs only the disposable `verification/` objects in that
bucket. Do not use a production runtime identity or grant project-wide Storage
Admin. Keep Cloud Run maximum instances at one while whole-file state persists.
Do not copy production users/sessions, filings, evidence, feedback labels or case
notes into staging. Seed only synthetic users and case fixtures.

## Prove permission boundaries using metadata

Before object tests, save private IAM metadata for the staging bucket, staging
service identity, and verification identity's effective project/folder/org
bindings. Use read-only policy inspection or IAM Policy Troubleshooter for
storage.objects.get on an unrelated bucket resource name; this inspects policy
and does not read any object. No test request should target a production bucket.
Record deny/allow findings and all inherited grants or conditional bindings.
Inspect actual role permissions, including custom roles and service-account
impersonation/delegation paths. Bucket IAM alone cannot prove absence of an
inherited broader grant. If ancestor policies or Troubleshooter evidence are
unavailable, report the isolation boundary as unverified; do not claim access to
unrelated buckets is denied merely because the harness never accessed them.

Use a short-lived impersonated verifier access token in MFI_STAGING_GCS_TOKEN
when available. The harness supports it without changing the user's ADC login.
Otherwise its SDK uses current ADC; root must verify and record that identity
before execution. Never print tokens or include them in receipts. Synthetic app
credentials may be read from the private JSON referenced by
MFI_STAGING_CREDENTIALS_FILE (username/password fields), or from
MFI_STAGING_USERNAME and MFI_STAGING_PASSWORD environment variables. Optional
MFI_STAGING_IAM_TOKEN is sent only as X-Serverless-Authorization for a private
Cloud Run invoker boundary. No token is persisted by the harness.

## Verify real Storage generation conflicts

```
G:/Python311/python.exe backend/scripts/verify_hosted_stage.py PRIVATE_RESOURCES.json --mode cas --execute --output PRIVATE_CAS_RECEIPT.json
```

A versioned intent receipt is written before mutation. The harness creates one
UUID-owned `verification/RUN_ID/cas.json` object with if_generation_match=0,
writes generation 2 from the known baseline, deliberately tries the stale
baseline and requires HTTP 412, confirms newer content was unchanged, explicitly
reloads/checks the current generation and commits a reconciled fixture. The final
receipt records exact object name, generation and checksum. It never lists the
bucket or fetches any unrelated object. There are no automatic retry loops.

If interrupted, preserve the intent receipt and inspect only that exact owned
object under the approved staging bucket. Reconcile the current generation
explicitly; do not broaden cleanup to a bucket or production prefix.

After preserving the completed receipt, optionally clean up only that object:

```
G:/Python311/python.exe backend/scripts/verify_hosted_stage.py PRIVATE_RESOURCES.json --mode cas-cleanup --execute --receipt PRIVATE_CAS_RECEIPT.json --output PRIVATE_CLEANUP_RECEIPT.json
```

Cleanup requires exact run ID/object path, original bucket, current expected
generation and matching content checksum. A changed object is preserved rather
than force-deleted. No recursive or wildcard deletion is performed.

## Verify application persistence on a fresh instance

```
G:/Python311/python.exe backend/scripts/verify_hosted_stage.py PRIVATE_RESOURCES.json --mode http-prepare --execute --output PRIVATE_APP_RECEIPT.json
```

The harness requires unauthenticated protected-route denial, a synthetic login,
authenticated /api/auth/me, a uniquely named synthetic saved search and synthetic
text evidence upload. Both writes require durable/pending acknowledgments;
evidence hash must match the submitted bytes. Only synthetic IDs, hashes and
acknowledgments enter the receipt. A missing persistence header is an acceptance
failure, not silently assumed durable. If a partial phase fails, inspect the
staging state before repeating; HTTP requests are not cross-record transactions.

For pending writes, inspect the staging admin persistence status and confirm the
relevant objects reached synced status before restart. Do not restart while the
only acknowledgment remains pending. Root then creates an approved staging-only
new revision/fresh instance with the same dedicated bucket (no production
change). Save before/after revision metadata and startup/instance evidence,
confirm old instances no longer receive requests, and place before_revision,
after_revision and fresh_instance_confirmed=true in a private restart evidence
JSON. The harness requires different revision names, but that marker is an
operator attestation; retain actual Cloud Run metadata/logs rather than inventing
it. A revision change alone is insufficient if traffic still reaches the old
instance. Recreate the exact staging proxy against the new revision if used.

```
G:/Python311/python.exe backend/scripts/verify_hosted_stage.py PRIVATE_RESOURCES.json --mode http-verify --execute --receipt PRIVATE_APP_RECEIPT.json --restart-evidence PRIVATE_RESTART_METADATA.json --output PRIVATE_RESTART_RESULT.json
```

Login is repeated against the fresh instance. The exact saved search must be
present. Evidence integrity and downloaded bytes must match the pre-restart
custody hash, proving cold rehydration from the staging bucket rather than a
surviving local cache. Read startup logs and fresh-instance provenance alongside
the harness result. No provider ranking, human fraud judgment, recoveries or
commercial accuracy is inferred by this infrastructure exercise.

Keep synthetic evidence and case metadata until receipts/logs are retained. There
is no blanket evidence deletion mode. Saved-search removal or destruction of the
dedicated staging service/bucket requires a separate exact-resource cleanup step
by root after evidence collection; never delete unrelated data or production
objects. Local receipts/credential references belong in ignored private paths,
not source control or public reports.
