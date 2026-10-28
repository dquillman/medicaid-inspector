# Medicaid Inspector: current status

This file tracks release validation and the approved production privacy repair. Production dataset configuration and storage privacy were repaired; the broader software remediation remains unreleased.

| Workstream | Current state |
| --- | --- |
| Production privacy | Repaired: operational storage blocks anonymous access and enforces public-access prevention. Only the public dataset is in its separate public bucket; both production services healthy on the new URL. Private-object HEAD checks return 403 |
| Software remediation | Implemented locally and deployed to private synthetic staging; not committed or released to production |
| Backend verification | 274 tests passed, including privacy policy preservation, public-source recurrence guards and production verification helpers |
| Frontend verification | 11 unit tests passed; TypeScript and Vite build passed |
| Original data preservation | 18 input artifacts preserved; post-rescore SHA-256 comparison confirms every original remains unchanged |
| Score and artifact refresh | Corrected-version rebuild complete for 117,956 providers; 126 scores changed from the first rebuild and 23 fewer exceed the review threshold. All five representative live/batch comparisons matched; derived analyses, indexes and model rebuilt |
| Backup/recovery | Coverage fixed; four disposable recovery tests passed |
| Network identity | All 4,523,582 rebuilt index entries checked: zero invalid center or neighbor identities; unavailable servicing identity does not erase billing self-totals |
| Hosted staging | Complete: private mfi-api-staging, anonymous access denied (403), real GCS conflicts/reconciliation passed. Saved search and evidence survived a new revision; evidence bytes verified by SHA256. Synthetic provider/source/artifact/network routes passed; temporary verifier permission removed |
| Local staged app | Final health, login, protected access, provider listing, ranking, network identity and artifact compatibility checks passed |
| Source-quality sample | Final repeatable 5,000-row check: 49 source-contract exceptions, 233 missing servicing identities, one high-value review flag. Raw values retained; incompatible codes cannot support specialty inference and invalid identities cannot form network links |
| Independent accuracy study | Current-version 50-case package retained under backend/private_evaluations/20261027-scoring-v2; all 55 inventory hashes verified, diagnostics coordinator-only. All judgments unresolved; evaluator rejects an accuracy claim |
| Production release | Privacy configuration repair completed on pinned existing images; older service needed memory raised from 512 MiB to 4 GiB after a verified startup OOM. Broader application-code release not performed |

## Remaining sequence

1. Completed: final isolated rescore, derived-artifact rebuild and five representative live/batch comparisons.
2. Completed: final local staged application, network and artifact compatibility checks; disposable recovery tests passed. Source exceptions remain visible data limitations; do not invent corrected identities or code mappings.
3. Completed: hosted recovery, synthetic data-route checks and approved production storage privacy repair. Historical access was not investigated; the completed repair prevents the verified public-storage access path going forward.
4. Run the blinded study with an investigator; software tests do not establish fraud accuracy or commercial value.
5. Review the release package before production deployment.

See [completed privacy repair](production-privacy-repair-results.md), [hosted results](hosted-staging-results.md), [local results](local-staging-results.md), [reviewer instructions](../backend/private_evaluations/20261027-scoring-v2/reviewer/START_HERE.md), and [validation protocol](validation-protocol.md).


