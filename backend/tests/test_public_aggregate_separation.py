"""Future releases separate public aggregate reads from private operational state."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from services.artifact_provenance import (
    assess_artifact, build_manifest, relocate_verified_aggregate_manifest,
    PRIVATE_LEGACY_AGGREGATE_URL, PUBLIC_AGGREGATE_URL,
)


def test_settings_default_uses_public_aggregate_bucket(monkeypatch):
    monkeypatch.delenv("PARQUET_URL", raising=False)
    from core.config import Settings
    assert Settings(_env_file=None).PARQUET_URL == PUBLIC_AGGREGATE_URL


def test_cli_deploy_explicitly_pins_public_aggregate_url(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "cli" / "mfi.py"
    spec = importlib.util.spec_from_file_location("fixture_mfi_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    commands = []
    monkeypatch.setattr(cli, "_run_shell", lambda command, **kwargs: commands.append(command) or 1)
    assert cli.cmd_deploy_backend(SimpleNamespace(skip_tests=True)) == 1
    command = commands[0]
    variables = command[command.index("--update-env-vars") + 1]
    assert "PARQUET_URL=" + PUBLIC_AGGREGATE_URL in variables
    assert PRIVATE_LEGACY_AGGREGATE_URL not in variables


def test_public_bucket_rejected_even_with_cached_operational_client(monkeypatch):
    from core import gcs_sync as sync
    class MustNotWrite:
        def blob(self, *args, **kwargs):
            raise AssertionError("Public bucket must never be accessed for operational I/O")
    monkeypatch.setattr(sync, "_BUCKET_NAME", "medicaid-inspector-public-aggregates")
    monkeypatch.setattr(sync, "_bucket", MustNotWrite())
    assert sync._get_bucket() is None
    assert not sync.upload_bytes("synthetic-state.json", b"{}")


def test_relocation_requires_explicit_equal_sha_receipt_and_keeps_dates(tmp_path):
    source = tmp_path / "synthetic.json"
    source.write_text("{}")
    data = {"generated_at": datetime.now(timezone.utc).isoformat(), "spec_version": "v1",
            "provenance": build_manifest(source, PRIVATE_LEGACY_AGGREGATE_URL, "v1")}
    assert not assess_artifact(data, "v1", source_url=PUBLIC_AGGREGATE_URL)["usable"]
    for checksum in ("KFYNRQ==", "short", "A" * 64):
        with pytest.raises(ValueError):
            relocate_verified_aggregate_manifest(data, source_sha256=checksum, destination_sha256=checksum,
                verified_at="2026-10-27T00:00:00Z", verification_reference="synthetic-receipt")
    with pytest.raises(ValueError):
        relocate_verified_aggregate_manifest(data, source_sha256="a" * 64, destination_sha256="b" * 64,
            verified_at="2026-10-27T00:00:00Z", verification_reference="synthetic-receipt")
    migrated = relocate_verified_aggregate_manifest(data, source_sha256="a" * 64, destination_sha256="a" * 64,
        verified_at="2026-10-27T00:00:00Z", verification_reference="retained-synthetic-checksum-receipt")
    assert data["provenance"]["source_url"] == PRIVATE_LEGACY_AGGREGATE_URL
    assert migrated["provenance"]["source_url"] == PUBLIC_AGGREGATE_URL
    assert migrated["generated_at"] == data["generated_at"]
    assert migrated["provenance"]["source_retrieved_at"] is None
    assert migrated["provenance"]["source_relocation_receipt"]["artifact_input_sha256"] == data["provenance"]["input"]["sha256"]
    assert assess_artifact(migrated, "v1", source_url=PUBLIC_AGGREGATE_URL)["usable"]
