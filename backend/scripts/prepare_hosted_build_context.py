"""Prepare a source-only Cloud Run build context locally; no cloud/build commands.

The canonical Dockerfile copies backend/. This explicit allowlist prevents
operator case files, credentials and local staging snapshots entering it.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

PACKAGES = {"core", "data", "routes", "services", "cli", "scripts"}
EXCLUDED_PARTS = {"tests", "test", "private_evaluations", "backups", "evidence", "credentials", "node_modules", "__pycache__", "venv"}
PUBLIC_REFERENCES = ("oig_exclusions.json", "npi_deactivations.json")
MAX_COPY_BYTES = 32 * 1024 * 1024


def _source_files(source):
    backend = source / "backend"
    yield source / "Dockerfile", Path("Dockerfile")
    yield backend / "requirements.txt", Path("backend/requirements.txt")
    for name in PUBLIC_REFERENCES:
        yield backend / name, Path("backend") / name
    for directory, subdirs, filenames in os.walk(backend):
        current = Path(directory)
        relative = current.relative_to(backend)
        subdirs[:] = [name for name in subdirs
                      if not name.startswith(".") and name not in EXCLUDED_PARTS
                      and (relative.parts or name in PACKAGES)
                      and not (current / name).is_symlink()]
        for name in filenames:
            path = current / name
            if not name.endswith(".py") or name.startswith("test_") or name == "conftest.py":
                continue
            if name.startswith(".") or path.is_symlink():
                continue
            yield path, Path("backend") / relative / name


def prepare_context(source_root: Path, output: Path):
    source = source_root.resolve()
    output = output.resolve()
    if not output.is_relative_to(source / "backend" / ".tmp"):
        raise ValueError("Output must be a new directory beneath source backend/.tmp")
    if output.exists():
        raise ValueError("Output exists; it will not be overwritten")
    candidates = list(_source_files(source))
    total = 0
    for path, _ in candidates:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("Required source input missing or not a regular in-repository file")
        total += path.stat().st_size
    if total > MAX_COPY_BYTES:
        raise ValueError("Source-only copy exceeds 32 MiB bound; inspect inputs before proceeding")
    output.mkdir(parents=True)
    inventory = []
    for path, relative in sorted(candidates, key=lambda item: str(item[1])):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        inventory.append({"path": relative.as_posix(), "bytes": destination.stat().st_size, "sha256": digest})
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "status": "source_context_prepared_no_build_or_deployment",
                "files": inventory, "file_count": len(inventory), "copied_bytes": total,
                "raw_fixture_present": False,
                "raw_data_test_status": "not_yet_deployable_for_raw_data_tests",
                "public_reference_allowlist": list(PUBLIC_REFERENCES),
                "limitations": ["No raw Parquet or derived operator cache is included.",
                                "No frontend build is included; this is the canonical backend-only Docker context.",
                                "Fresh staging credentials, private bucket and explicit env settings remain required.",
                                "A valid local fixture larger than 1 MB is required by the current raw-data loader."]}
    (output / "build-context-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "STAGING-CONTEXT.txt").write_text(
        "Prepared source-only backend context. No build/deploy performed.\n"
        "Raw-data tests are NOT ready: no local Parquet fixture is included.\n"
        "Use only an approved staging project/service/bucket and fresh staging secret.\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = prepare_context(args.source_root, args.output)
    print(json.dumps({key: manifest[key] for key in ("status", "file_count", "copied_bytes", "raw_fixture_present", "raw_data_test_status")}))


if __name__ == "__main__":
    main()
