"""Versioned provenance for derived public-data artifacts. No network or writes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from copy import deepcopy

MANIFEST_VERSION = 1
TRANSFORM_VERSION = "public-aggregate-evidence-v1"
SCHEMA_VERSION = "hhs-provider-hcpcs-month-v1"
PRIVATE_LEGACY_AGGREGATE_URL = "https://storage.googleapis.com/medicaid-inspector-data/medicaid-provider-spending.parquet"
PUBLIC_AGGREGATE_URL = "https://storage.googleapis.com/medicaid-inspector-public-aggregates/medicaid-provider-spending.parquet"


def relocate_verified_aggregate_manifest(data: dict, *, source_sha256: str,
                                         destination_sha256: str, verified_at: str,
                                         verification_reference: str) -> dict:
    """Explicit local metadata migration after independent same-byte verification.

    This performs no I/O and does not establish the caller's checksum evidence.
    CRC32C, equal names, and matching sizes alone do not satisfy this contract.
    The caller must retain its verification receipt. No automatic URL aliasing.
    """
    def valid_digest(value):
        return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    manifest = data.get("provenance") or {}
    if manifest.get("source_url") != PRIVATE_LEGACY_AGGREGATE_URL:
        raise ValueError("Only the explicit legacy-to-public aggregate relocation is supported")
    if not valid_digest(source_sha256) or source_sha256 != destination_sha256:
        raise ValueError("Equal verified SHA256 digests are required")
    input_checksum = (manifest.get("input") or {}).get("sha256")
    if not valid_digest(input_checksum) or not str(verification_reference or "").strip():
        raise ValueError("Artifact input checksum and retained verification reference are required")
    timestamp = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Verification timestamp must have a timezone")
    migrated = deepcopy(data)
    migrated["provenance"]["source_url"] = PUBLIC_AGGREGATE_URL
    migrated["provenance"]["source_relocation_receipt"] = {
        "version": 1, "from_url": PRIVATE_LEGACY_AGGREGATE_URL,
        "to_url": PUBLIC_AGGREGATE_URL, "source_sha256": source_sha256,
        "destination_sha256": destination_sha256, "artifact_input_sha256": input_checksum,
        "verified_at": verified_at, "verification_reference": verification_reference,
    }
    # Never reset generated_at or upstream retrieval dates to imply fresh data.
    return migrated


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(cache_path: Path, dataset_url: str, spec_version: str, coverage: dict | None = None,
                   enrichment_path: Path | None = None) -> dict:
    """Hash the actual transformation input; never invent a source retrieval date.

    Input-file mtime is recorded as such, not as proof of upstream freshness.
    """
    return {
        "manifest_version": MANIFEST_VERSION,
        "transform_version": TRANSFORM_VERSION,
        "detector_version": spec_version,
        "program": "Medicaid",
        "source_url": dataset_url,
        "source_retrieved_at": None,
        "coverage": coverage or {"start": None, "end": None, "basis": "unknown"},
        "schema_version": SCHEMA_VERSION,
        "enrichment_input": ({"filename": enrichment_path.name, "sha256": file_sha256(enrichment_path)}
                             if enrichment_path is not None and enrichment_path.exists() else None),
        "input": {"filename": cache_path.name, "sha256": file_sha256(cache_path),
                  "file_modified_at": datetime.fromtimestamp(cache_path.stat().st_mtime, timezone.utc).isoformat()},
        "limitations": ["Beneficiary cell counts are not deduplicated across source rows.",
                        "No claim lines, diagnoses, modifiers, or beneficiary identities.",
                        "Upstream retrieval time is unknown; build time does not establish source freshness."],
    }


def assess_artifact(data: dict, detector_version: str, now: datetime | None = None, source_url: str | None = None) -> dict:
    errors: list[str] = []
    if not isinstance(data, dict):
        data = {}
    raw_manifest = data.get("provenance")
    manifest = raw_manifest if isinstance(raw_manifest, dict) else {}
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        errors.append("missing_or_incompatible_manifest")
    if manifest.get("transform_version") != TRANSFORM_VERSION:
        errors.append("incompatible_transformation")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("incompatible_schema")
    if data.get("spec_version") != detector_version or manifest.get("detector_version") != detector_version:
        errors.append("incompatible_detector")
    raw_input = manifest.get("input")
    checksum = raw_input.get("sha256", "") if isinstance(raw_input, dict) else ""
    if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        errors.append("missing_input_checksum")
    if manifest.get("program") != "Medicaid" or not manifest.get("source_url"):
        errors.append("unknown_source_scope")
    if source_url is not None and manifest.get("source_url") != source_url:
        errors.append("source_dataset_changed")
    age_days = None
    try:
        generated = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        if generated.tzinfo is None:
            raise ValueError("timezone required")
        age_days = ((now or datetime.now(timezone.utc)) - generated).total_seconds() / 86400
        if age_days < -1:
            errors.append("future_build_timestamp")
    except (KeyError, TypeError, ValueError):
        errors.append("unknown_build_timestamp")
    return {"usable": not errors, "errors": errors, "build_age_days": age_days,
            "is_stale": age_days is None or age_days > 30,
            "source_freshness": "unknown" if not manifest.get("source_retrieved_at") else "recorded",
            "provenance": manifest}
