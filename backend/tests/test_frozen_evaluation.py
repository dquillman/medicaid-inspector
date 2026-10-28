import pytest
from services.evaluation import freeze_ranking, evaluate_frozen_sample


def sample(k=50):
    return freeze_ranking([{"npi": f"fixture-{i}", "risk_score": 100-i} for i in range(k)], snapshot_id="frozen-test", provenance={"dataset_sha256": "fixture"}, k=k)


def finding(case_id, outcome):
    return {"case_id": case_id, "outcome": outcome, "evidence_reference": "agency record", "reviewer": "independent", "review_date": "2026-10-26"}


def test_unresolved_denominator_never_becomes_precision_at50():
    manifest = sample()
    results = evaluate_frozen_sample(manifest, [finding(manifest["private_rows"][0]["case_id"], "substantiated")])
    assert results["unresolved"] == 49
    assert results["precision_at_50"] is None
    assert results["full_sample_precision_bounds"] == [0.02, 1.0]
    assert results["resolved_case_fraction"] == 1.0


def test_complete_sample_and_blinding():
    manifest = sample()
    findings = [finding(row["case_id"], "substantiated" if row["rank"] <= 10 else "unsubstantiated") for row in manifest["private_rows"]]
    assert evaluate_frozen_sample(manifest, findings)["precision_at_50"] == 0.2
    assert all(isinstance(case, str) for case in manifest["blinded_order"])
    assert manifest["blinded_order"] != [row["case_id"] for row in manifest["private_rows"]]


def test_manifest_tamper_duplicate_and_unsupported_outcomes_rejected():
    manifest = sample()
    case = manifest["private_rows"][0]["case_id"]
    with pytest.raises(ValueError):
        evaluate_frozen_sample(manifest, [finding(case, "criminal_charges")])
    with pytest.raises(ValueError):
        evaluate_frozen_sample(manifest, [finding(case, "substantiated")] * 2)
    manifest["private_rows"][0]["rank"] = 99
    with pytest.raises(ValueError, match="hash"):
        evaluate_frozen_sample(manifest, [])


def test_missing_evidence_and_short_sample_are_not_precision50():
    manifest = sample(2)
    case = manifest["private_rows"][0]["case_id"]
    with pytest.raises(ValueError, match="evidence"):
        evaluate_frozen_sample(manifest, [{"case_id": case, "outcome": "substantiated"}])
    findings = [finding(row["case_id"], "substantiated") for row in manifest["private_rows"]]
    assert evaluate_frozen_sample(manifest, findings)["precision_at_50"] is None


def test_complete_review_gate_and_snapshot_binding():
    from services.evaluation import evaluate_review_document
    manifest = sample()
    document = {"snapshot_id": manifest["snapshot_id"], "manifest_sha256": manifest["manifest_sha256"], "adjudications": []}
    with pytest.raises(ValueError, match="Incomplete"):
        evaluate_review_document(manifest, document, require_complete=True)
    partial = evaluate_review_document(manifest, document)
    assert partial["accuracy_proven"] is False
    assert partial["precision_at_50"] is None
    document["snapshot_id"] = "different"
    with pytest.raises(ValueError, match="matching"):
        evaluate_review_document(manifest, document)


def test_evaluator_command_rejects_missing_judgments(tmp_path, capsys):
    import json
    from scripts.evaluate_frozen_review import main
    manifest = sample()
    manifest_path = tmp_path / "manifest.json"
    review_path = tmp_path / "review.json"
    manifest_path.write_text(json.dumps(manifest))
    review_path.write_text(json.dumps({"snapshot_id": manifest["snapshot_id"], "manifest_sha256": manifest["manifest_sha256"], "adjudications": []}))
    assert main([str(manifest_path), str(review_path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["accuracy_proven"] is False
    assert result["evaluation_status"] == "rejected"
    assert "fixture-" not in json.dumps(result)
    assert main([str(manifest_path), str(review_path), "--allow-incomplete"]) == 0
    assert json.loads(capsys.readouterr().out)["unresolved"] == 50


def test_retained_package_preserves_hashes_blinding_and_source(tmp_path):
    import hashlib
    import json
    from scripts.retain_evaluation_package import retain, verify_retained_package
    manifest = sample(2)
    source = tmp_path / "source"
    source.mkdir()
    (source / "factual_packets").mkdir()
    (source / "private_manifest.json").write_text(json.dumps(manifest))
    review = {"snapshot_id": manifest["snapshot_id"], "manifest_sha256": manifest["manifest_sha256"], "adjudications": [{"case_id": case, "outcome": "unresolved"} for case in manifest["blinded_order"]]}
    (source / "blinded_review.json").write_text(json.dumps(review))
    for case in manifest["blinded_order"]:
        (source / "factual_packets" / (case + ".json")).write_text(json.dumps({"case_id": case, "subject": {"npi": "fixture"}, "published_aggregates": {"total_paid": 5}}))
    destination = tmp_path / "retained"
    diagnostic = tmp_path / "source-quality-private.json"
    diagnostic.write_text(json.dumps({"selection_seed": 42, "sample_hash": "fixture-hash", "raw_provider": "private-fixture"}))
    result = retain(source, destination, version_label="synthetic-v1", source_quality=diagnostic)
    assert result["unresolved"] == 2
    assert result["source_quality_retained"] is True
    assert not (destination / "reviewer" / "source-quality-private.json").exists()
    private_diagnostic = destination / "coordinator_only" / "source-quality-private.json"
    assert private_diagnostic.read_bytes() == diagnostic.read_bytes()
    assert verify_retained_package(destination)["verified"] is True
    assert (source / "private_manifest.json").exists()
    assert not (destination / "reviewer" / "private_manifest.json").exists()
    custody = json.loads((destination / "retention_manifest.json").read_text())
    for name, digest in custody["file_sha256"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    private_diagnostic.write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_retained_package(destination)
    with pytest.raises(ValueError, match="already exists"):
        retain(source, destination, version_label="no-overwrite")
    packet = source / "factual_packets" / (manifest["blinded_order"][0] + ".json")
    packet.write_text(json.dumps({"case_id": manifest["blinded_order"][0], "risk_score": 99}))
    with pytest.raises(ValueError, match="model"):
        retain(source, tmp_path / "leaky", version_label="reject")


def test_smoke_evaluation_names_are_single_safe_basenames():
    from scripts.smoke_stage import validate_evaluation_name
    assert validate_evaluation_name("evaluation-v2") == "evaluation-v2"
    for value in ("../private", "a/b", "a\\b", ".", "", "C:drive"):
        with pytest.raises(ValueError): validate_evaluation_name(value)
