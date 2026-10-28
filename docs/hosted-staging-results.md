# Hosted staging verification — October 27, 2026

The private staging API is deployed in `us-central1` as `mfi-api-staging`. Its dedicated bucket has public access prevention enabled, and its runtime identity and fresh admin secret are separate from production. No production service, data object, Hosting site or permission was changed.

The image contains reviewed source plus explicitly synthetic billing/enrichment: 256 fixture providers and 129,024 monthly aggregate rows. Public reference snapshots are unchanged. No operator cases, credentials, trained models or investigator outcomes were copied. This tests functionality and durability, not fraud accuracy.

## Verified outcomes

- Build `09977cb0-e86c-4be5-8a7f-5514e72c7074` succeeded. Image digest: `sha256:2b6e30b1af7a363fe2cc9fd0358e54956e475fecf4db2d903994d7671009bd57`.
- Anonymous staging requests return 403. Protected app routes also reject requests lacking app authentication; synthetic admin login succeeds inside the IAM boundary.
- Real GCS generation-conflict test ran as the staging runtime identity: stale write rejected, newer bytes preserved, explicit reconciliation succeeded. Its one disposable object was removed only after exact generation/checksum verification. Soft deletion may retain it temporarily.
- A synthetic saved search and text evidence upload both received durable-storage acknowledgments.
- New revision `mfi-api-staging-00002-9c4` received 100% of traffic after `mfi-api-staging-00001-lnx`. The saved search and evidence record survived; the downloaded evidence bytes matched the original SHA256 hash after fresh-instance recovery.
- Sizing: one CPU, 4 GiB, concurrency four, min instances zero, revision max instances one, request-based CPU. Background jobs and paid integration keys are disabled.

Private receipts are retained under `backend/private_validations/20261027-hosted/`: CAS, exact-object cleanup, HTTP prepare, restart metadata, HTTP recovery and the synthetic data-route report, plus read-only IAM evidence. All eight retained file hashes verified. They contain synthetic IDs, hashes and resource metadata; credentials are fetched into memory and omitted. Source receipts also remain under `backend/.tmp/hosted-verification-20261027/`.

The first Cloud SDK proxy attempt required an unavailable install permission; direct authenticated requests were used instead. The credential wrapper now preserves the SDK's own interpreter after proving that forcing the app's Python caused a missing-cryptography failure. Four wrapper regression tests and live in-memory token retrieval passed.

Additional hosted checks passed with HTTP 200 for public methods, the 256-provider synthetic list, source validation, artifact diagnostics and network lookup. The synthetic 5,000-row sample had zero format exceptions and recorded DuckDB 2.0.0; this is not an accuracy finding about real providers. The deployed artifact was compatible. The final isolated backend suite passed 264 tests; frontend verification remains 11 passing tests and a successful build.

After verification, the temporary Token Creator grant on the staging service-account resource was removed and its absence verified. No project-wide or production IAM binding changed. Private staging resources remain available with min instances zero; storage, secrets and later usage may still incur charges.

## Production privacy finding — subsequently repaired

The production public-read finding was subsequently repaired under explicit approval. Both production services now use a dedicated public dataset-only bucket; operational storage no longer grants anonymous access and enforces public-access prevention. Existing private objects return 403 anonymously. See [completed repair](production-privacy-repair-results.md). No production object contents were read to test the privacy finding or its closure.

See [provisioning evidence](hosted-staging-provisioning.md), [privacy repair plan](production-privacy-repair-plan.md) and [investigator validation protocol](validation-protocol.md). Production release and human adjudication remain separate steps.
