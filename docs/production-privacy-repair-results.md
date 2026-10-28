# Production storage privacy repair — completed October 27, 2026

Completed under explicit user approval. Production continues using the real public aggregate dataset; synthetic data remains confined to staging. Current production application images were retained. This was a configuration/IAM repair, not the release of the broader uncommitted software remediation.

## Storage and source verification

- Copied only `medicaid-provider-spending.parquet` from pinned source generation `1774579251010800` into the dedicated `medicaid-inspector-public-aggregates` bucket. The destination generation is `1793145740967808`; size 2,940,234,191 bytes and CRC32C `KFYNRQ==` match. This was a generation-guarded server-side copy, not a claimed SHA256 comparison.
- Verified that the new public bucket contains exactly that one allowlisted object. No operational JSON, database, evidence or case records were copied there.
- Removed `allUsers` object-viewer access from `medicaid-inspector-data`, preserved every nonpublic binding, and enabled bucket public-access prevention. Uniform bucket-level access remains enabled. No project-wide IAM grants changed.
- Anonymous HEAD requests to the known-existing `users.json` and `app.db` now return 403. Their contents were never downloaded for verification.
- The new public dataset returns HEAD 200 and range 206 with the Parquet header. DuckDB verified seven source columns, metadata for 227,083,361 rows and 2,257 row groups, and a bounded aggregate query over the first 1,000 rows. No provider-level records entered the verification report.

## Production services

| Service | Ready revision | Traffic | Health/readiness | Application version |
| --- | --- | --- | --- | --- |
| medicaid-inspector-api | medicaid-inspector-api-00190-n4h | 100% | 200 / 200 | 3.62.9 |
| medicaid-inspector | medicaid-inspector-00006-jzq | 100% | 200 / 200 | 2.1.5 |

Both services explicitly use `https://storage.googleapis.com/medicaid-inspector-public-aggregates/medicaid-provider-spending.parquet`. Their existing immutable images, secrets, runtime identities and unrelated environment settings were preserved. The older service initially exceeded its 512 MiB memory limit while loading existing state. Its memory was increased to the project's established 4 GiB sizing; startup and readiness then passed. This resource change can increase its active-memory cost. Its image was not rebuilt or replaced with newer application code.

Protected admin routes return 401 without app authentication on both services. Verification created no application login/session and performed no case or referral action. Effective source URL and revision/image settings were verified through Cloud Run metadata; authenticated in-app source diagnostics were deliberately not queried. Runtime Storage SDK permissions remain through the existing account's explicit object-admin grant; no separate authenticated private-object content test was performed.

## Recurrence protection and retained evidence

Local defaults, CLI deployment, shell deployment, Cloud Build and the standalone downloader now point to the dedicated public dataset. Operational persistence rejects that public bucket as a state destination. Strict provenance source matching remains in place: unreleased derived artifacts naming the old source URL require verified migration or rebuilding before the broader software release. No production derived cache was rewritten for this repair.

Final isolated backend suite: **274 passed**, with two existing Pydantic deprecation warnings. Read-only production HTTP/source checks all passed. Private policy backups, exact copy metadata, cutover comparisons, startup failure evidence and final verification receipts are retained under `backend/private_validations/20261027-privacy-repair/`, excluded from Git and deployment contexts.

This closes the verified public-storage access path going forward. It does not establish whether data was accessed before the repair; historical access review was not performed. Independent investigator adjudication and the broader software production release remain outstanding.
