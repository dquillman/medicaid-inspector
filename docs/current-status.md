# Medicaid Inspector: current status

**v3.62.10 is live and verified — October 28, 2026.** [Open the app](https://medicaid-inspector.web.app). Existing users must sign in again.

| Workstream | Status |
| --- | --- |
| Software | Committed, pushed and deployed to production |
| Real-data refresh | 117,956 corrected provider scores and five derived artifacts deployed; live version and compatibility checks passed |
| Privacy | Operational storage blocks anonymous access; public aggregate dataset separate; duplicate endpoint private |
| Sessions | Earlier tokens revoked on both revisions; persisted sessions empty after verification logout |
| Cases | Database, review queue, referrals, tips, watchlist and four other operator objects unchanged |
| Verification | 279 backend tests, 12 frontend unit tests, TypeScript/build and live checks passed |
| Website | Version 3.62.10; deployed bundle matches local build exactly |
| Historical access | No access-log records returned; prior access remains unknown because logging coverage was not established |
| Staging | Synthetic hosted recovery checks complete; production uses real data |
| Accuracy study | Prepared 50-case blinded package; all outcomes unresolved, requires investigator adjudication |

## What remains

1. Investigator review of the 50 blinded cases. Agents cannot supply independent judgments.
2. Change any reused local password as a precaution. Passwords were preserved, not rotated. The canonical admin credential is managed through Secret Manager; other local accounts can use account controls.

Production npm audit reports zero advisories. Whole-file persistence still requires one active writer; development-tool alerts remain a separate maintenance concern.

Automatic background case preparation and enrichment are disabled. The main app is the supported operator entry point. No referral, tip, case-status change or investigation outcome was submitted by this release.

See [release details](release-3.62.10.md), [exposure review](exposure-review.md), and [reviewer instructions](../backend/private_evaluations/20261027-scoring-v2/reviewer/START_HERE.md).
