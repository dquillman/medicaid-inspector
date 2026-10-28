# Review remediation: implementation and verification

The review's actionable software changes are implemented locally. This is not a production release or an effectiveness study. Existing operator data, case records, scores, and derived artifacts were not rewritten.

## Implemented

| Area | Result |
| --- | --- |
| Evidence validity | Aggregate hypotheses no longer add independent corroboration points. Exports preserve unknown/error states; scores and correlated flags alone do not establish referral readiness. |
| Scoring parity | Live and scan paths share a detector runner and canonical dominant-code, whole-provider cohorts. Newly computed scores record versions, exact peer statistics and source identity limitations. Local cohort caching invalidates on source/spec changes. |
| Source validation | Schema and type contracts, billing/servicing identity, monthly coverage, HCPCS, missing/nonfinite amounts, integer counts, beneficiary suppression states and repeated source-grain keys are checked. Aggregate key repeats are not labeled duplicate clinical claims. |
| Denominators | UI, reports and CSV labels distinguish summed beneficiary cell counts from deduplicated people. Legacy API fields remain compatible. |
| Labels | Tip/referral filing and analyst suspicion are not verified fraud outcomes. Documented substantiated/unsubstantiated findings need evidence references. Corrections and withdrawals preserve signal snapshots and invalidate incompatible model predictions. |
| Evaluation | Offline frozen-ranking sample generator, manifest hash validation, blinded identifiers, independent adjudication protocol, unresolved-case bounds and explicit conditions for precision-at-50. No accuracy results were fabricated. |
| Provenance | Derived artifacts record detector/schema/transformation versions, input and slim-enrichment hashes, observed coverage and unknown upstream retrieval dates. Missing, malformed or incompatible artifacts cannot silently reuse old cached validation. |
| Age and program scope | Older evidence remains discoverable; DOJ age filtering is reversible. Medicare administrative facts are distinguished from Medicaid eligibility and questioned payments from established losses. |
| Evidence and persistence | Investigator permission for evidence uploads; atomic metadata and rollback protection; GCS generation preconditions; consistent SQLite backup snapshots; request-specific failure/pending/durable acknowledgments and UI warnings. |
| Test isolation | Tests run from a temporary source-only checkout, strip credentials, disable background work, block external networking and refuse accidental direct execution beside operator data. CI uses the isolated runner. |

## Verified

- Full backend suite: **216 passed** using `G:\Python311\python.exe backend/scripts/run_isolated_tests.py tests -q --tb=short`.
- Frontend application/API suite: **11 passed** using `node node_modules/vitest/vitest.mjs run src/__tests__ --reporter=dot` from `frontend`.
- `npm run build`: TypeScript and Vite passed.
- `git diff --check`: passed.
- Read-only local Parquet metadata matched the source schema contract. The first 1,000 rows had no source identity/month/HCPCS contract issues, observed beneficiary counts, and no repeated aggregate keys. This sequential slice is not representative validation of the complete dataset or fraud detection.
- A separate integration review identified and corrected an evidence rollback race, missing schema compatibility enforcement, and omitted slim-enrichment provenance.

The sandbox prevented Windows asyncio's local event-loop socket from functioning. Async tests were therefore run outside that sandbox through the source-only runner, with external networking still blocked. No production application startup or cloud operation was performed.

## Remaining operational and human validation, in priority order

1. Before release, perform a controlled local rescore and derived-artifact rebuild with the new versions; inspect representative score changes and preserve old snapshots. Existing legacy artifacts are deliberately marked incompatible rather than retroactively assigned provenance. Source build time never proves upstream freshness.
2. Execute the blinded investigator study in `validation-protocol.md`, obtain independently documented outcomes, and compare actionable leads and preparation time with the investigator's current workflow. No independent precision, recovery, commercial ROI, or agency action has been established by these changes.
3. Verify real bucket IAM/generation behavior, backup restoration, deployment restarts and authenticated served UI in staging before production deployment. Offline tests do not establish those properties.
4. Keep deployment limited to one instance. Generation checks prevent stale overwrite but do not merge records or provide cross-file transactions. A record-level transactional store and controlled migration remain necessary before expanding concurrent multiuser use; no cloud infrastructure was provisioned.

The sales campaign remains paused. No tips, referrals, emails or other external submissions were sent. Changes remain available for local review; no deployment was performed.
