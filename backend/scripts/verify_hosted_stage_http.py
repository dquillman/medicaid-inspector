"""Execute HTTP checks only against the approved private MFI staging service.

Fetches IAM identity token and exact staging Secret Manager version into memory.
Never prints CLI output, response bodies, passwords or tokens. Root executes it;
importing this module performs no network request or credential access.
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys

_EXPECTED = {"project_id": "medicaid-inspector", "service_name": "mfi-api-staging",
             "bucket": "medicaid-inspector-staging-validation",
             "service_url": "https://mfi-api-staging-jpsql7yh2q-uc.a.run.app"}
_SECRET = "mfi-staging-admin-password"
_SECRET_VERSION = "1"


class StagingVerificationError(RuntimeError):
    """Allowlisted phase only; never includes CLI/HTTP exception contents."""
    def __init__(self, phase):
        self.phase = phase
        super().__init__("Hosted staging phase failed")


def _resolve_cli() -> str:
    cli = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if cli:
        return cli
    known = pathlib.Path("G:/Program Files (x86)/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd")
    if known.is_file():
        return str(known)
    raise StagingVerificationError("cli_resolution")


def _capture(cli: str, arguments: list[str]) -> str:
    environment = dict(os.environ)
    # Preserve Cloud SDK's interpreter/environment selection. Live comparison
    # showed its default succeeds, while forcing this app's Python fails because
    # that interpreter lacks cryptography required by gcloud auth. Do not inject
    # an application interpreter or reorder PATH for the SDK.
    for name in ("MFI_STAGING_PASSWORD", "MFI_STAGING_IAM_TOKEN", "MFI_STAGING_CREDENTIALS_FILE"):
        environment.pop(name, None)
    phase = "identity_token" if arguments[0] == "auth" else "admin_secret"
    try:
        result = subprocess.run([cli, *arguments], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False, env=environment)
    except OSError:
        raise StagingVerificationError(phase + "_cli_launch") from None
    if result.returncode:
        raise StagingVerificationError(phase + "_cli_nonzero")
    if not result.stdout:
        raise StagingVerificationError(phase + "_cli_empty")
    return result.stdout.decode("utf-8").rstrip("\r\n")


def run(resources: pathlib.Path, *, mode: str, output: pathlib.Path,
        receipt: pathlib.Path | None = None, restart_evidence: pathlib.Path | None = None,
        username: str = "admin") -> int:
    # Exact immutable resource allowlist prevents config-selected production
    # requests or arbitrary Secret Manager reads with the caller's identity.
    config = json.loads(resources.read_text(encoding="utf-8"))
    if config.get("approved_staging_only") is not True or any(config.get(key) != value for key, value in _EXPECTED.items()) or config.get("proxy_url"):
        raise ValueError("Wrapper accepts only the explicitly approved direct staging resources")
    if mode not in ("http-prepare", "http-verify"):
        raise ValueError("Only staging HTTP prepare/verify modes are permitted")
    if mode == "http-verify" and (receipt is None or restart_evidence is None):
        raise ValueError("Prior synthetic receipt and fresh-instance metadata required")
    if output.exists() or output.with_suffix(output.suffix + ".intent.json").exists():
        raise ValueError("Use new versioned output receipts")
    cli = _resolve_cli()
    identity_token = password = None
    names = ("MFI_STAGING_IAM_TOKEN", "MFI_STAGING_USERNAME", "MFI_STAGING_PASSWORD", "MFI_STAGING_CREDENTIALS_FILE")
    old = {name: os.environ.get(name) for name in names}
    try:
        # Both CLI commands execute before placing secrets in environment, so
        # credentials are not inherited by a later credential-fetch process.
        identity_token = _capture(cli, ["auth", "print-identity-token", "--quiet"])
        password = _capture(cli, ["secrets", "versions", "access", _SECRET_VERSION,
                                  "--secret=" + _SECRET, "--project=" + _EXPECTED["project_id"], "--quiet"])
        if not identity_token.strip() or not password: raise RuntimeError("Empty staging credential")
        os.environ.update(MFI_STAGING_IAM_TOKEN=identity_token,
                          MFI_STAGING_USERNAME=username, MFI_STAGING_PASSWORD=password)
        os.environ.pop("MFI_STAGING_CREDENTIALS_FILE", None)
        try:
            from scripts import verify_hosted_stage as harness
        except ModuleNotFoundError:
            import verify_hosted_stage as harness
        arguments = [str(resources), "--mode", mode, "--execute", "--output", str(output)]
        if receipt is not None: arguments += ["--receipt", str(receipt)]
        if restart_evidence is not None: arguments += ["--restart-evidence", str(restart_evidence)]
        # Harness receipts contain only synthetic IDs, hashes and metadata.
        # Suppress all console data so future helper changes cannot expose a
        # response body or credential via this wrapper's stdout/stderr.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return harness.main(arguments)
            except (Exception, SystemExit):
                raise StagingVerificationError(mode.replace("-", "_")) from None
    finally:
        for name, previous in old.items():
            if previous is None: os.environ.pop(name, None)
            else: os.environ[name] = previous
        identity_token = password = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=pathlib.Path)
    parser.add_argument("--mode", required=True, choices=["http-prepare", "http-verify"])
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--receipt", type=pathlib.Path)
    parser.add_argument("--restart-evidence", type=pathlib.Path)
    parser.add_argument("--username", default="admin")
    args = parser.parse_args(argv)
    try:
        result = run(args.resources, mode=args.mode, output=args.output,
                     receipt=args.receipt, restart_evidence=args.restart_evidence,
                     username=args.username)
        print("HOSTED_STAGING_HTTP_COMPLETE" if result == 0 else "HOSTED_STAGING_HTTP_FAILED")
        return result
    except StagingVerificationError as error:
        print("HOSTED_STAGING_HTTP_FAILED phase=" + error.phase + "; sensitive details suppressed")
        return 1
    except (Exception, SystemExit):
        print("HOSTED_STAGING_HTTP_FAILED phase=preflight_or_configuration; sensitive details suppressed")
        return 1


if __name__ == "__main__": raise SystemExit(main())
