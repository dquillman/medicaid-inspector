"""Offline evaluator. Complete outcomes required unless --allow-incomplete.

Prints aggregate results only; no provider identities. Does not contact agencies
or validate whether a supplied evidence reference substantiates a finding.
"""
import argparse
import json
import pathlib
import sys
_BACKEND = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path: sys.path.insert(0, str(_BACKEND))


def main(argv=None) -> int:
    from services.evaluation import evaluate_review_document
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("review", type=pathlib.Path)
    parser.add_argument("--package-root", type=pathlib.Path, help="Verify retained packet and private diagnostic checksums before evaluation")
    parser.add_argument("--allow-incomplete", action="store_true", help="Report unresolved counts/bounds only; never treat as accuracy proof")
    args = parser.parse_args(argv)
    try:
        if args.package_root is not None:
            from scripts.retain_evaluation_package import verify_retained_package
            verify_retained_package(args.package_root)
            if args.manifest.resolve() != (args.package_root / "coordinator_only" / "private_manifest.json").resolve():
                raise ValueError("Manifest must belong to the verified retained package")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        review = json.loads(args.review.read_text(encoding="utf-8"))
        result = evaluate_review_document(manifest, review, require_complete=not args.allow_incomplete)
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"evaluation_status": "rejected", "accuracy_proven": False,
                          "reason": "Review is incomplete, mismatched or invalid. Check frozen inventory, every case judgment, and evidence/reviewer/date fields. No accuracy claim is available."}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
