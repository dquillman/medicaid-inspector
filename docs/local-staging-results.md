# Final local staging results

Local run completed October 27, 2026. Source changes remain uncommitted. A subsequent private hosted staging deployment is documented in [hosted results](hosted-staging-results.md); production remains unchanged.

- Corrected scoring version: `shared-15-detectors-aggregate-denominator-v2-code-system-guard`. Rebuilt 117,956 providers, derived analyses, slim cache, HCPCS/network indexes and anomaly scores. Compared with the first corrected rebuild, 126 scores changed and 23 fewer providers exceeded the review threshold (9,875 versus 9,898). These are screening changes, not established fraud findings.
- All five representative live/batch comparisons matched scores and signals. Five records do not prove whole-dataset parity.
- Final local API checks passed: health, public methods, synthetic login, authenticated data quality, ranking, provider listing and network identity. Unauthenticated admin access returned 401; artifact provenance was compatible.
- The entire rebuilt network index was checked: 4,523,582 entries, zero invalid center or neighbor identities. Missing servicing identity does not erase billing self-totals. NPI checksums do not verify registry identity, ownership or improper payment.
- Final deterministic source sample: 5,000 rows, 4,951 passing and 49 source-contract exceptions. There were 233 missing servicing identities, 39 malformed servicing identities, eight alternate-code-system shapes, one malformed code and two malformed billing identities; categories may overlap. One high-value aggregate was a separate review flag. No repeated source-grain keys occurred in this sample.
- Incompatible source codes cannot support specialty-mismatch inference. Unavailable or invalid identities cannot form billing/servicing network links. Raw source values remain preserved; no guessed code padding or invented identities.
- Sampling uses vectorized typed hashing with deterministic tie-breaks and a recorded DuckDB version. SHA256 protects the selected sample and capped private diagnostics. The original per-row JSON/cryptographic selection was replaced after proving too slow on the full source.
- Ranking evaluated 117,388 eligible providers. Fifty current-version factual packets and blinded judgments were retained under `backend/private_evaluations/20261027-scoring-v2`, separate from scores and coordinator diagnostics. All 55 custody inventory hashes verified. All 50 outcomes remain unresolved; the evaluator correctly rejects accuracy claims from incomplete review.
- All 18 original input artifacts still matched their pre-refresh SHA256 hashes after final checks. Recovery testing used disposable fixtures.
- Final verification: 245 backend tests passed; 11 frontend unit tests passed; TypeScript/Vite build passed. Remaining warnings concern Pydantic deprecations, older Browserslist metadata and existing bundle size.

Earlier random and separately seeded diagnostic samples are historical checks, not this final sample. Their counts should not be compared as if they contained the same rows. First-version review material remains retained separately.

Private machine-readable reports remain under `backend/.tmp/release-validation-piyug920/backend/`. The durable current review package also retains the final source-quality diagnostic snapshot exclusively for its coordinator.

The original source-only context was subsequently extended with synthetic fixtures and deployed to private hosted staging. Real GCS conflict/recovery and hosted synthetic data checks passed. Production storage privacy was subsequently repaired under explicit approval; the latest regression suite passed 274 tests. See [hosted results](hosted-staging-results.md) and [privacy repair](production-privacy-repair-results.md). Independent investigator review and the broader application-code release remain outstanding.
