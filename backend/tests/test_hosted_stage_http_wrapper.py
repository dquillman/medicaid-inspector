import json
import os
from scripts import verify_hosted_stage_http as wrapper
from scripts import verify_hosted_stage as harness


def test_wrapper_fetches_only_staging_secret_and_restores_memory_environment(tmp_path, monkeypatch, capsys):
    resource = tmp_path / "resources.json"
    resource.write_text(json.dumps({"approved_staging_only": True, **wrapper._EXPECTED}))
    calls = []
    monkeypatch.setattr(wrapper.shutil, "which", lambda _: "fake-gcloud")
    def capture(cli, arguments):
        calls.append(arguments)
        return "sensitive-identity" if arguments[0] == "auth" else "sensitive-password"
    monkeypatch.setattr(wrapper, "_capture", capture)
    monkeypatch.setenv("MFI_STAGING_PASSWORD", "original-password")
    monkeypatch.setenv("MFI_STAGING_CREDENTIALS_FILE", "original-reference")
    def execute(arguments):
        assert os.environ["MFI_STAGING_PASSWORD"] == "sensitive-password"
        assert os.environ["MFI_STAGING_IAM_TOKEN"] == "sensitive-identity"
        assert "MFI_STAGING_CREDENTIALS_FILE" not in os.environ
        print("sensitive-password")
        return 0
    monkeypatch.setattr(harness, "main", execute)
    assert wrapper.main([str(resource), "--mode", "http-prepare", "--output", str(tmp_path / "receipt.json")]) == 0
    assert calls[1] == ["secrets", "versions", "access", "1", "--secret=mfi-staging-admin-password", "--project=medicaid-inspector", "--quiet"]
    assert os.environ["MFI_STAGING_PASSWORD"] == "original-password"
    assert os.environ["MFI_STAGING_CREDENTIALS_FILE"] == "original-reference"
    assert capsys.readouterr().out.strip() == "HOSTED_STAGING_HTTP_COMPLETE"


def test_wrapper_rejects_other_resource_before_fetch_and_suppresses_errors(tmp_path, monkeypatch, capsys):
    resource = tmp_path / "resources.json"
    config = {"approved_staging_only": True, **wrapper._EXPECTED}; config["bucket"] = "production"
    resource.write_text(json.dumps(config))
    monkeypatch.setattr(wrapper, "_capture", lambda *args: (_ for _ in ()).throw(AssertionError("Must not fetch credentials")))
    assert wrapper.main([str(resource), "--mode", "http-prepare", "--output", str(tmp_path / "receipt.json")]) == 1
    assert "production" not in capsys.readouterr().out


def test_cli_child_preserves_sdk_interpreter_and_path_without_secrets(monkeypatch):
    import subprocess
    original = os.environ.get("PATH")
    monkeypatch.setenv("CLOUDSDK_PYTHON", "sdk-selected-interpreter")
    monkeypatch.setenv("MFI_STAGING_PASSWORD", "must-not-reach-cli")
    def fake_run(arguments, **kwargs):
        assert kwargs["env"]["CLOUDSDK_PYTHON"] == "sdk-selected-interpreter"
        assert "MFI_STAGING_PASSWORD" not in kwargs["env"]
        assert kwargs["env"]["PATH"] == original
        return subprocess.CompletedProcess(arguments, 0, stdout=b"synthetic-token", stderr=b"sensitive-warning")
    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper._capture("fake-gcloud.cmd", ["auth", "print-identity-token"]) == "synthetic-token"
    assert os.environ.get("PATH") == original


def test_safe_cli_failure_reports_only_allowlisted_phase(monkeypatch):
    import subprocess
    import pytest
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stdout=b"secret", stderr=b"credential-content"))
    with pytest.raises(wrapper.StagingVerificationError) as failure:
        wrapper._capture("fake", ["secrets", "versions", "access", "1"])
    assert failure.value.phase == "admin_secret_cli_nonzero"
    assert "credential-content" not in str(failure.value)
