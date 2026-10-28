# Independent frozen-sample validation

Status: protocol and tooling implemented; no effectiveness study has been run by this change. No measured fraud-detection accuracy, agency success, recovery or ROI is asserted.

## Prepare and freeze

1. A coordinator captures the exact current ranking once, including dataset/source coverage, retrieval dates, dataset hashes, detector/cohort/scoring versions and capture time. Do not refresh between selection and review. Existing case actions may bias the ranking; record its inclusion/exclusion rules.
2. Supply that captured ranking and provenance to `backend/scripts/build_evaluation_sample.py`. This is an offline command using a supplied JSON file, not application startup. It exclusively creates a private hashed manifest and a blank blinded review template in a new directory. Use a fresh snapshot ID and directory; never overwrite a sample. The pure functions in `backend/services/evaluation.py` can also be used directly without disk or network access.
3. The private manifest seals rank, scores and identifier mapping. Keep it with the coordinator. Reviewers receive opaque case IDs in hash order and evidence packets scrubbed of score, rank, flags, app narratives and allegation language. Reviewers necessarily need provider identity to check outside sources; only the coordinator's mapping may disclose it. Opaque IDs alone are not complete blinding if an evidence packet leaks ranking cues.
4. Freeze 50 cases for precision-at-50. A smaller set remains a smaller pilot, explicitly identified. Separately freeze a random or matched comparison group before review if estimating ranking lift; a top-only sample cannot estimate recall or population prevalence. Related owners/addresses can create dependent cases: record clusters and use cluster-level resampling or group-based splits in a larger study.

## Review and adjudicate

Use two independent reviewers where available. Record reviewer, review date, source reference, time spent, factual observations, alternative explanations and missing evidence separately from the conclusion. Reviewers must not see each other's judgment until both are submitted. An adjudicator resolves disagreement, retaining both original judgments and the reason for resolution in an append-only record. If independent reviewers are unavailable, describe the exercise as internal review rather than independent validation.

Two distinct endpoints must remain separate:

- **Actionable investigation lead:** a documented factual discrepancy worth a specific next investigative step. Define criteria before review, including alternative explanations and availability of additional evidence. This is useful operational evidence, not a fraud label and not training ground truth.
- **Agency substantiation outcome:** documented independent substantiated or unsubstantiated findings. Pending cases, declined referrals, settlements, charges, a civil action, analyst suspicion and app-generated assertions are unresolved for this endpoint. A reference must point to the underlying agency/case record and establish the finding's program, identity and period; entering reference text does not itself verify the claim.

An unsubstantiated outcome does not prove no fraud occurred; retain its agency definition and limitations. Do not collapse lack of evidence into a negative finding. Do not infer outcomes from publicity or filing status alone.

## Calculate and report

Pass the unchanged private manifest and adjudicated rows to `evaluate_frozen_sample`. It checks the manifest hash, rejects duplicate/foreign cases and unsupported outcome categories, and requires evidence reference, reviewer and date for definitive findings. It performs no network access and produces no new labels itself.

Report the full denominator, substantiated, unsubstantiated, unresolved and resolution rate. Missing reviews remain unresolved. Report full-sample bounds: substantiated / sample size through (substantiated + unresolved) / sample size. The resolved-case fraction is explicitly conditional and can be biased by which cases resolve. The utility returns precision-at-50 only when exactly 50 frozen cases have definitive outcomes. Its Wilson interval describes the resolved subset under independent-case assumptions; it does not correct outcome selection or network correlation. Do not present it as a calibrated population estimate.

Measure operational usefulness separately: actionable leads per analyst hour, unsupported allegations, duplicate leads, evidence gaps and packet preparation time. Compare the same tasks and reviewers against spreadsheet triage using randomized/counterbalanced task assignment. Predefine success thresholds with the operator before collecting results; do not choose thresholds after seeing the scores. Store duration per task and report median and spread, not an invented ROI conversion.

## Model validation limits

The model's current cross-validation is internal stratified validation over documented referral outcomes. Scaling is fitted within each fold, preventing preprocessing leakage. It is still a small selected convenience sample, potentially containing related providers and features influenced by earlier scoring/feedback. It does not demonstrate temporal generalization, independent investigator performance, calibrated fraud probability or population recall. Until enough independently labeled groups exist, retain these limitations prominently rather than manufacturing a stronger statistic. For a future benchmark, freeze features before outcome availability and hold out entire provider/ownership clusters and later time periods; do not tune against the final holdout.


## Retained investigator handoff

Frozen packets are retained locally outside disposable staging under the ignored
`backend/private_evaluations/` directory. This path is excluded from Git, Docker
build contexts and gcloud upload contexts. Local retention is not encryption,
remote backup or permission enforcement. Apply workstation access controls and
an authorized private backup process; do not publish these provider packets.

Each version has separate `coordinator_only/` and `reviewer/` directories plus a
`retention_manifest.json` containing file hashes. Give investigators only the
reviewer directory, which includes START_HERE.md, factual packets and the blank
review template. Keep model ordering and the sealed manifest coordinator-only.
Store completed reviewer and adjudicator submissions as new versioned files;
preserve the original template and independent reviewer judgments.

The v1 package is explicitly frozen before the specialty-code scoring correction.
A later v2 package is a separate sample; never replace v1's ranks, facts or labels
with v2 results, and do not combine their denominators without a predefined study.

From repository root, evaluate the returned review with:

```
G:/Python311/python.exe backend/scripts/evaluate_frozen_review.py backend/private_evaluations/PACKAGE/coordinator_only/private_manifest.json RETURNED_REVIEW.json
```

The command requires snapshot/hash binding, all sampled judgments, no unresolved
outcomes, and evidence/reviewer/date fields for definitive findings. An incomplete
or invalid review returns exit 2 and explicitly reports `accuracy_proven: false`.
For an honest progress report only, add `--allow-incomplete`; unresolved cases stay
in the denominator, precision-at-50 stays unavailable, and bounds remain visible.
Even a completed top-50 review does not establish general classification accuracy.
The tool cannot verify a claimed agency finding merely because a reference was
entered: independent human evidence checks and adjudication remain necessary.

Retain an existing frozen package without creating outcomes:

```
G:/Python311/python.exe backend/scripts/retain_evaluation_package.py SOURCE_EVALUATION_DIRECTORY backend/private_evaluations/NEW_PACKAGE --version-label SCORING_VERSION
```

Retention rejects mismatched packet inventories, model-cue keys, changed initial
blinded ordering and overwriting an existing package. Original staged artifacts
remain untouched. `smoke_stage.py --evaluation-name evaluation-v2` creates a
separate evaluation directory on a later authorized staging run.


For source-quality traceability, retention accepts `--source-quality PATH` for
the smoke run's `scratch/smoke-auth-*/source-quality-private.json`. Its exact
bytes and seeded selection/sample-hash metadata remain exclusively under
`coordinator_only/source-quality-private.json`, included in the retained checksum
inventory. Never provide these diagnostics to blinded reviewers. Optional
`evaluate_frozen_review.py --package-root PACKAGE` verifies the entire retained
packet and diagnostic inventory before evaluating judgments. Checksums detect
changes against the retained inventory; the inventory is not digitally signed.
