"""Freeze a supplied ranking offline, without loading the application or stores.

Usage: python scripts/build_evaluation_sample.py ranking.json output-folder --snapshot-id NAME
Input: {"ranking": [{"npi": "...", "brain_score": 1}], "provenance": {...}}
This command never refreshes rankings, calls providers or infers outcomes.
"""
import argparse
import json
import pathlib
import sys

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def main() -> int:
    from services.evaluation import freeze_ranking
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ranking_json", type=pathlib.Path)
    parser.add_argument("output_directory", type=pathlib.Path)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--k", type=int, default=50)
    args = parser.parse_args()
    supplied = json.loads(args.ranking_json.read_text(encoding="utf-8"))
    manifest = freeze_ranking(supplied["ranking"], snapshot_id=args.snapshot_id, provenance=supplied["provenance"], k=args.k)
    # Fail before writing if either frozen output already exists.
    args.output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_directory / "private_manifest.json"
    review_path = args.output_directory / "blinded_review.json"
    if manifest_path.exists() or review_path.exists():
        parser.error("Frozen outputs already exist; choose a new directory")
    review = [{"case_id": case, "outcome": "unresolved", "evidence_reference": "", "reviewer": "", "review_date": "", "notes": ""} for case in manifest["blinded_order"]]
    with manifest_path.open("x", encoding="utf-8") as target:
        json.dump(manifest, target, indent=2)
    with review_path.open("x", encoding="utf-8") as target:
        json.dump(review, target, indent=2)
    print(f"Frozen {manifest['sample_size']} cases. Keep private_manifest.json sealed from reviewers; see docs/validation-protocol.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
