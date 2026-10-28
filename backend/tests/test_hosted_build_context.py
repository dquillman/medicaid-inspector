"""Synthetic allowlist validation; no operator files or cloud calls."""
from pathlib import Path
import pytest
from scripts.prepare_hosted_build_context import prepare_context, PUBLIC_REFERENCES


def synthetic_source(tmp_path):
    root = tmp_path / "source"
    backend = root / "backend"
    backend.mkdir(parents=True)
    (root / "Dockerfile").write_text("COPY backend/ /app")
    (backend / "requirements.txt").write_text("fastapi")
    (backend / "main.py").write_text("app = None")
    for name in PUBLIC_REFERENCES:
        (backend / name).write_text("{}")
    return root


def test_only_source_and_explicit_public_reference_files_are_copied(tmp_path):
    source = synthetic_source(tmp_path)
    backend = source / "backend"
    forbidden = ["users.json", "sessions.json", "app.db", ".env", "case.json", "data/source.parquet",
                 ".tmp/old-stage/secret.py", "private_evaluations/mapping.py", "tests/test_case.py",
                 "services/tests/test_nested.py", "credentials/secret.py", "test_ad_hoc.py", "logs/operator.py"]
    for name in forbidden:
        path = backend / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE")
    allowed = backend / "services" / "detector.py"
    allowed.parent.mkdir(exist_ok=True)
    allowed.write_text("pass")
    output = backend / ".tmp" / "prepared"
    result = prepare_context(source, output)
    paths = {item["path"] for item in result["files"]}
    assert "backend/services/detector.py" in paths
    assert "backend/main.py" in paths
    assert all("backend/" + name not in paths for name in forbidden)
    assert {item for item in paths if item.endswith(".json")} == {"backend/" + name for name in PUBLIC_REFERENCES}
    assert not result["raw_fixture_present"]
    assert result["raw_data_test_status"] == "not_yet_deployable_for_raw_data_tests"
    assert all(len(item["sha256"]) == 64 for item in result["files"])


def test_output_guard_and_overwrite_refusal(tmp_path):
    source = synthetic_source(tmp_path)
    with pytest.raises(ValueError, match="beneath"):
        prepare_context(source, tmp_path / "outside")
    output = source / "backend" / ".tmp" / "prepared"
    prepare_context(source, output)
    with pytest.raises(ValueError, match="exists"):
        prepare_context(source, output)


def test_missing_public_reference_fails_before_copy(tmp_path):
    source = synthetic_source(tmp_path)
    (source / "backend" / PUBLIC_REFERENCES[0]).unlink()
    output = source / "backend" / ".tmp" / "prepared"
    with pytest.raises(ValueError, match="missing"):
        prepare_context(source, output)
    assert not output.exists()
