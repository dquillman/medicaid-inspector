from datetime import datetime, timezone
import json

from services.artifact_provenance import assess_artifact, build_manifest, file_sha256


def test_manifest_hashes_input_without_inventing_retrieval_date(tmp_path):
    source = tmp_path / "scan.json"
    source.write_text('{"providers": []}')
    manifest = build_manifest(source, "https://example.test/medicaid.parquet", "v1")
    data = {"generated_at": datetime.now(timezone.utc).isoformat(), "spec_version": "v1", "provenance": manifest}
    result = assess_artifact(data, "v1")
    assert result["usable"]
    assert manifest["input"]["sha256"] == file_sha256(source)
    assert result["source_freshness"] == "unknown"


def test_legacy_artifact_is_not_verified_by_recent_build_date():
    result = assess_artifact({"generated_at": datetime.now(timezone.utc).isoformat()}, "v2")
    assert not result["usable"]
    assert "missing_or_incompatible_manifest" in result["errors"]


def test_loader_refuses_changed_detector_and_exposes_reason(tmp_path, monkeypatch):
    from services import precomputed_store as store
    path = tmp_path / "derived.json"
    path.write_text(json.dumps({"generated_at": "2026-01-01T00:00:00Z", "spec_version": "old", "claim_patterns": {"modifiers": [1]}}))
    monkeypatch.setattr(store, "_PATH", path)
    monkeypatch.setattr(store, "_state", {"data": None, "mtime": 0})
    assert store.get_precomputed("claim_patterns") is None
    assert not store.get_staleness_info()["validation"]["usable"]


def test_missing_and_nonfinite_amounts_are_not_valid():
    from services.data_validator import validate_claim_amount
    assert "amount_missing" in validate_claim_amount(None)
    assert "amount_not_finite" in validate_claim_amount(float("nan"))
    assert "amount_not_finite" in validate_claim_amount(float("inf"))


def test_unknown_schema_and_changed_dataset_are_rejected(tmp_path):
    source = tmp_path / "cache.json"
    source.write_text("{}")
    manifest = build_manifest(source, "https://example.test/original", "v1")
    manifest["schema_version"] = "unknown-future-schema"
    result = assess_artifact({"provenance": manifest, "spec_version": "v1",
                              "generated_at": datetime.now(timezone.utc).isoformat()},
                             "v1", source_url="https://example.test/replacement")
    assert not result["usable"]
    assert {"incompatible_schema", "source_dataset_changed"} <= set(result["errors"])


def test_enrichment_input_changes_manifest_checksum(tmp_path):
    source, enrichment = tmp_path / "cache.json", tmp_path / "slim.json"
    source.write_text("{}")
    enrichment.write_text('{"specialty": "A"}')
    first = build_manifest(source, "https://example.test/input", "v1", enrichment_path=enrichment)
    enrichment.write_text('{"specialty": "B"}')
    second = build_manifest(source, "https://example.test/input", "v1", enrichment_path=enrichment)
    assert first["input"] == second["input"]
    assert first["enrichment_input"]["sha256"] != second["enrichment_input"]["sha256"]


def test_removed_or_corrupt_artifact_cannot_reuse_cached_validation(tmp_path, monkeypatch):
    from services import precomputed_store as store
    path = tmp_path / "artifact.json"
    monkeypatch.setattr(store, "_PATH", path)
    monkeypatch.setattr(store, "_state", {"data": {"generated_at": "old"}, "mtime": 1})
    assert store.get_precomputed("generated_at") is None
    assert store._state["data"] is None
    path.write_text("[]")
    assert store.get_precomputed("generated_at") is None
    assert not store.get_staleness_info()["validation"]["usable"]
    assert not assess_artifact({"provenance": "malformed"}, "v1")["usable"]


def test_metadata_failure_does_not_leave_visible_evidence(tmp_path, monkeypatch):
    from core import evidence_store as store
    monkeypatch.setattr(store, "_EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(store, "_evidence", {})
    monkeypatch.setattr(store, "_ALLOW_LOCAL_ONLY", True)

    def fail():
        assert store._lock.locked(), "Metadata failure and rollback must remain in the mutation lock"
        raise store.EvidenceStorageError("disk unavailable")

    monkeypatch.setattr(store, "_save_to_disk", fail)
    import pytest
    with pytest.raises(store.EvidenceStorageError):
        store.add_evidence("test-case", "proof.txt", b"test", "investigator")
    assert store.get_evidence_list("test-case") == []
    assert not list(tmp_path.glob("*.txt"))


def test_metadata_upload_failure_is_not_success(tmp_path, monkeypatch):
    from core import evidence_store as store, gcs_sync
    monkeypatch.setattr(store, "_META_FILE", tmp_path / "metadata.json")
    monkeypatch.setattr(store, "_ALLOW_LOCAL_ONLY", False)
    monkeypatch.setattr(gcs_sync, "upload_bytes", lambda *a, **k: False)
    import pytest
    with pytest.raises(store.EvidenceStorageError):
        store._save_to_disk()


def test_viewer_cannot_upload_case_evidence(client, auth_headers):
    import uuid
    name = "read_only_" + uuid.uuid4().hex[:10]
    created = client.post("/api/auth/users", headers=auth_headers,
                          json={"username": name, "password": "fixture-pass123", "role": "viewer"})
    assert created.status_code == 200
    logged = client.post("/api/auth/login", json={"username": name, "password": "fixture-pass123"})
    token = logged.json()["token"]
    response = client.post("/api/cases/test-case/evidence",
                           headers={"Authorization": "Bearer " + token},
                           files={"file": ("test.txt", b"fixture")})
    assert response.status_code == 403
