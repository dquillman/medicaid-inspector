"""Retain a frozen evaluation privately without changing cases or outcomes.

Copies only expected evaluation files, validates model blinding keys and binds
review templates to the sealed manifest. Never contacts a provider or agency.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys
_BACKEND = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path: sys.path.insert(0, str(_BACKEND))

INVESTIGATOR_INSTRUCTIONS = """# Independent investigator review

You receive factual packets and a blank review template. Ranks, scores, detector
flags, prior case decisions and app-generated allegations are withheld. Packet
filenames and template order use opaque case IDs. Subject identity supports
independent source verification; do not publish or circulate the private data.

1. Copy blinded_review.json to a new reviewer-specific working file. Keep the
   template and factual packets unchanged. Do not request coordinator files or
   use the application's ranking/narrative while making the initial judgment.
2. For each case, verify source coverage dates, Medicaid versus Medicare program,
   provider identity, applicable period, aggregate-denominator limitations and
   alternative explanations. Record factual discrepancies separately from fraud.
3. Enter substantiated or unsubstantiated only for an independently documented
   agency finding. Record reviewer, ISO review_date, and an evidence_reference to
   the underlying agency/case record establishing identity, program and period.
   A referral, charges, settlement, declined submission or analyst suspicion is
   not a substantiation label. Unknown or inaccessible evidence stays unresolved.
4. Use notes to record missing evidence, alternative explanations and limitations.
   Optionally record investigation minutes and actionable next steps separately;
   usefulness is not proof of fraud and does not become a training label.
5. Where two reviewers are available, complete judgments independently first.
   Coordinator/adjudicator retains both originals and resolves disagreement in a
   separate versioned file; never replace originals with the final judgment.
6. Return the review file privately to the coordinator. Do not submit referrals,
   contact agencies, or change provider records as part of this review exercise.

The coordinator runs the offline evaluator. Missing/unresolved cases cannot be
presented as accuracy proof. Even complete top-50 substantiation is a selected
ranking metric, not population accuracy, recall, calibrated fraud probability,
recoveries or ROI. Source-only aggregates require further investigation.
"""


def _check_blind(value):
    forbidden = {"risk_score", "brain_score", "score", "rank", "flags", "signal_results", "fraud_probability", "evidence_class", "queue_status"}
    if isinstance(value, dict):
        if forbidden.intersection(value): raise ValueError("Packet includes model or prior-decision cues")
        for nested in value.values(): _check_blind(nested)
    elif isinstance(value, list):
        for nested in value: _check_blind(nested)


def retain(source: pathlib.Path, destination: pathlib.Path, *, version_label: str, source_quality: pathlib.Path | None = None) -> dict:
    from services.evaluation import evaluate_review_document
    manifest_path = source / "private_manifest.json"
    review_path = source / "blinded_review.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    result = evaluate_review_document(manifest, review)
    case_ids = set(manifest["blinded_order"])
    if [row.get("case_id") for row in review["adjudications"]] != manifest["blinded_order"]:
        raise ValueError("Initial review template must retain blinded case order")
    packets = source / "factual_packets"
    actual = {path.stem for path in packets.glob("*.json")}
    if actual != case_ids: raise ValueError("Packet inventory does not match frozen sample")
    inputs = [manifest_path, review_path]
    if source_quality is not None:
        # Coordinator diagnostics may contain provider identities and selection
        # metadata. Validate JSON, retain exact bytes, never copy to reviewers.
        diagnostic = json.loads(source_quality.read_text(encoding="utf-8"))
        if not isinstance(diagnostic, dict): raise ValueError("Source quality diagnostic must be a JSON object")
        inputs.append(source_quality)
    for case in manifest["blinded_order"]:
        path = packets / (case + ".json")
        packet = json.loads(path.read_text(encoding="utf-8"))
        if packet.get("case_id") != case: raise ValueError("Packet case identity mismatch")
        _check_blind(packet)
        inputs.append(path)
    if any(path.is_symlink() for path in inputs): raise ValueError("Symlinked package inputs are not allowed")
    if destination.exists(): raise ValueError("Retained package already exists; choose a new directory")
    destination.mkdir(parents=True)
    coordinator = destination / "coordinator_only"
    reviewer = destination / "reviewer"
    coordinator.mkdir()
    (reviewer / "factual_packets").mkdir(parents=True)
    shutil.copyfile(manifest_path, coordinator / manifest_path.name)
    if source_quality is not None:
        shutil.copyfile(source_quality, coordinator / "source-quality-private.json")
    shutil.copyfile(review_path, reviewer / review_path.name)
    for case in manifest["blinded_order"]:
        shutil.copyfile(packets / (case + ".json"), reviewer / "factual_packets" / (case + ".json"))
    (reviewer / "START_HERE.md").write_text(INVESTIGATOR_INSTRUCTIONS, encoding="utf-8")
    (coordinator / "START_HERE.md").write_text("""# Coordinator only

Do not share this directory with reviewers. It contains the frozen mapping and
model ordering. Provide only the reviewer directory for the initial assessment.
Keep each returned review as a new file. Retain originals and adjudicator notes.
Run from repository root:

G:/Python311/python.exe backend/scripts/evaluate_frozen_review.py PACKAGE/coordinator_only/private_manifest.json RETURNED_REVIEW.json

Default rejects incomplete judgments (exit 2). Add --allow-incomplete only to
report unresolved counts and bounds; this is not accuracy proof. Reference text
is a human attestation, not automated verification of the agency finding.

Package files are excluded from Git but not encrypted or backed up remotely.
Apply workstation access controls and an authorized private backup process.
""", encoding="utf-8")
    inventory = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file(): inventory[path.relative_to(destination).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    custody = {"version_label": version_label, "manifest_sha256": manifest["manifest_sha256"],
               "sample_size": result["sample_size"], "unresolved": result["unresolved"],
               "accuracy_proven": False, "source_quality_retained": source_quality is not None, "file_sha256": inventory}
    (destination / "retention_manifest.json").write_text(json.dumps(custody, indent=2), encoding="utf-8")
    return {"sample_size": result["sample_size"], "unresolved": result["unresolved"], "accuracy_proven": False,
            "retained_files": len(inventory) + 1, "source_quality_retained": source_quality is not None, "destination": str(destination)}


def verify_retained_package(directory: pathlib.Path) -> dict:
    """Verify custody inventory without printing diagnostic/provider contents.

    Hashes detect accidental changes against the retained inventory; this is
    not a signed, adversary-proof attestation of who created the package.
    """
    custody = json.loads((directory / "retention_manifest.json").read_text(encoding="utf-8"))
    expected = custody.get("file_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Retained package has no checksum inventory")
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file() and path.relative_to(directory).as_posix() != "retention_manifest.json"}
    if actual != set(expected): raise ValueError("Retained package file inventory changed")
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Retained package has an unsafe path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Retained package checksum mismatch")
    return {"verified": True, "hashed_files": len(expected), "source_quality_retained": bool(custody.get("source_quality_retained")), "accuracy_proven": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--version-label", required=True)
    parser.add_argument("--source-quality", type=pathlib.Path, help="Private smoke source-quality JSON; retained only for coordinator")
    args = parser.parse_args(argv)
    print(json.dumps(retain(args.source, args.destination, version_label=args.version_label, source_quality=args.source_quality), indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
