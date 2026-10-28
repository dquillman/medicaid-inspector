# Medicaid Inspector v3.62.10 â€” released October 28, 2026

Production uses real aggregate data; synthetic data remains in private staging.

| Item | Verified result |
| --- | --- |
| Backend source | 9db8777 (following 908a5f7 and 5e7bf36), pushed to origin/main |
| Main API | medicaid-inspector-api-00193-fvz; 100% traffic; health/readiness 200; version 3.62.10 |
| Older duplicate | medicaid-inspector-00009-2sj; same image and session cutoff; private IAM; anonymous requests return 403 |
| Image digest | sha256:cf0f0e3c2e92970fb88d212acee9d02b7dc0bde3c96ee0d4a1c87eb500263f58 |
| Website | https://medicaid-inspector.web.app; assets/index-BCaw4_ns.js; exact local/live byte match |
| Bundle SHA256 | ae34f55cf481dfe5c9d895f41996ee18bd462239c00805d12a13e84433f202eb |
| Checks | 279 isolated backend tests; 12 frontend unit tests; TypeScript/build; authenticated production smoke |
| Tag | Not created |

Authenticated login returned durable acknowledgement. The protected source endpoint verified 227,083,361 real rows and the dedicated public aggregate URL. A cached provider's corrected score/version matched the staged result. Derived-artifact compatibility, network identity and the 15-signal methods route passed. Hosting API rewrites work; anonymous admin access returns 401. These are bounded smoke checks, not exhaustive UI or fraud-accuracy proof.

Five refreshed derived artifacts were uploaded with generation preconditions: the 117,956-provider slim cache, precomputed analyses, HCPCS/network indexes and anomaly scores. Prior generations were backed up under private release-backups/20261028-v3.62.10/. Analyses were rebuilt against exact current input hashes for the new source URL. The legacy full-cache object remains preserved; production serves the refreshed slim cache. No old case snapshot overwrote current cases.

Independent local/public dataset SHA256 checks matched: a998e5ae11a391f1eb0d8464b3866a3ee7fe18aa13e56d411c50e72e3a0e35c7, 2,940,234,191 bytes. Public generation: 1793145740967808. Verification build: 4080aadb-9132-49ee-bbb0-b9a354bb6532. Backend build: b710aa30-b582-4b28-8bdf-af6a4f19f3c0.

The database, review queue, referrals, tips, watchlist, feedback, alert rules, auto-preparation state and bug log retained their original object generations. Existing users were retained. Credential values were not retained in receipts.

Both revisions enforce session cutoff 1793164209 at load, lookup and persistence. Earlier sessions remain invalid even if stale state is republished. Persisted sessions were cleared without reading token contents; the verification login was logged out and the final session object is empty. Users must sign in again. Login and logout uploads now bypass debounce and complete during request CPU; the sign-out button calls server revocation. Existing passwords were preserved; rotation is not claimed. For the canonical admin account, rotate its Secret Manager credential: startup intentionally resynchronizes that account from ADMIN_PASSWORD. Other local accounts can use their account password controls.

Operational storage enforces public-access prevention. Anonymous HEAD requests for users.json, app.db and sessions.json return 403. The duplicate endpoint is private. Automatic background case preparation/enrichment is disabled, and each service is capped at one instance. The main public app is the supported operator entry point; do not use the duplicate as another writing operator session. Whole-file persistence uses optimistic concurrency, not transactions.

The 30-day access-log query returned no records; no project auditConfigs were configured. Prior access remains unknown. Missing logs do not establish that no access occurred. See [exposure review](exposure-review.md).

## Remaining human work and maintenance

1. Investigator adjudication of the retained 50-case blinded package. Every outcome remains unresolved; no accuracy claim is supported. Frozen package files/hashes were preserved.
2. Change any reused local password as a precaution: hashes were potentially readable while the former storage grant existed. This release revoked sessions but did not rotate passwords or Google credentials.
3. Production npm dependency audit now reports zero advisories after updating the router. This is limited to the production npm dependency graph; it is not a claim that all GitHub/Python/development-tool alerts are resolved. Existing render benchmarks log caught fixture-shape errors; their passing result is not UI-workflow proof.

Source-quality exceptions and aggregate-only limitations remain visible. Neither a score nor filing a tip establishes fraud. Private receipts are in backend/private_validations/20261027-release/, excluded from Git and images.

The app now opens directly to investigator sign-in. Closed registration and obsolete trial/marketing counts are absent from the entry flow. Public methodology remains accessible. Navigation and no-trial regression checks passed. Router compatibility reference: [official changelog](https://reactrouter.com/changelog).

Final methodology verification confirmed explicit private case boundaries, no unsupported 12-claim suppression assertion, and no strongest-predictor claim. Login and logout both returned HTTP 200 with durable acknowledgement.
