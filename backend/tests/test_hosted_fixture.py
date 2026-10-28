"""Hosted fixtures contain synthetic aggregates and unchanged public references only."""
import json
import pytest
from core.identity_contract import is_valid_npi
from scripts import prepare_hosted_fixture as fixture
from services.artifact_provenance import assess_artifact, file_sha256
from services.claim_patterns import SPEC_VERSION


def test_generated_hosted_fixture_meets_real_loader_contract(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "oig_exclusions.json").write_text("{}", encoding="utf-8")
    (backend / "users.json").write_text("OPERATOR_MUST_NOT_COPY", encoding="utf-8")
    (backend / "review_queue.json").write_text("OPERATOR_MUST_NOT_COPY", encoding="utf-8")
    monkeypatch.setattr(fixture, "_BACKEND", backend)
    output = backend / ".tmp" / "hosted-synthetic"
    manifest = fixture.build_fixture(output)
    assert manifest["counts"] == {"providers": 256, "months": 84, "hcpcs_codes": 6,
                                  "aggregate_rows": 129024, "network_index_rows": 768,
                                  "operator_cases": 0, "outcomes": 0}
    source = output / "data" / "medicaid-provider-spending.parquet"
    assert source.stat().st_size > 1000000
    with source.open("rb") as stream:
        assert stream.read(4) == b"PAR1"
    slim = json.loads((output / "prescan_slim.json").read_text())
    assert all(is_valid_npi(row["npi"]) and row["npi"].startswith("9") for row in slim["providers"])
    assert all(row["synthetic_fixture"] and "NOT A REAL PROVIDER" in row["provider_name"] for row in slim["providers"])
    assert all(row["scoring_metadata"]["status"] == "synthetic_fixture_unscored" for row in slim["providers"])
    derived = json.loads((output / "precomputed_analyses.json").read_text())
    assert assess_artifact(derived, SPEC_VERSION, source_url=fixture.SOURCE_URL)["usable"]
    assert derived["provenance"]["synthetic_fixture"]
    assert not (output / "users.json").exists() and not (output / "app.db").exists()
    assert json.loads((output / "review_queue.json").read_text()) == {"items": []}
    assert (output / "oig_exclusions.json").read_bytes() == (backend / "oig_exclusions.json").read_bytes()
    for entry in manifest["files"]:
        assert file_sha256(output / entry["path"]) == entry["sha256"]
    with pytest.raises(ValueError):
        fixture.build_fixture(output)


def test_fixture_rejects_reference_identity_collisions_before_writing(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    identifier = next("900000000" + str(digit) for digit in range(10) if is_valid_npi("900000000" + str(digit)))
    (backend / "oig_exclusions.json").write_text(json.dumps({identifier: {"fixture_only": True}}))
    monkeypatch.setattr(fixture, "_BACKEND", backend)
    output = backend / ".tmp" / "must-not-create"
    with pytest.raises(ValueError, match="collides"):
        fixture.build_fixture(output)
    assert not output.exists()


def test_fixture_refuses_unscoped_paths_and_nonstaging_source(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, "_BACKEND", tmp_path)
    with pytest.raises(ValueError):
        fixture.build_fixture(tmp_path / "outside")
    with pytest.raises(ValueError):
        fixture.build_fixture(tmp_path / ".tmp" / "fixture", source_url="https://example.org/operator.parquet")
