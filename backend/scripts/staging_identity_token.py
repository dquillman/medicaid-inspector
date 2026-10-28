"""Memory-only staging Storage token helper. Never prints an access token."""
from __future__ import annotations
import shutil
import subprocess

STAGING_SERVICE_ACCOUNT = "mfi-runtime-staging@medicaid-inspector.iam.gserviceaccount.com"


def get_staging_storage_token() -> str:
    """Return a short-lived Storage-scoped token to an in-process verifier.

    Caller must not print/log/persist the return value or HTTP Authorization
    headers. This helper cannot select a production runtime identity.
    """
    cli = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not cli:
        raise RuntimeError("Google Cloud CLI not available")
    result = subprocess.run([cli, "auth", "print-access-token",
                             f"--impersonate-service-account={STAGING_SERVICE_ACCOUNT}",
                             "--scopes=https://www.googleapis.com/auth/devstorage.read_write", "--quiet"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Staging Storage token unavailable; CLI error output suppressed to protect credentials")
    return result.stdout.decode("utf-8").strip()


if __name__ == "__main__":
    value = get_staging_storage_token()
    print("STAGING_STORAGE_TOKEN_AVAILABLE" if value else "STAGING_STORAGE_TOKEN_UNAVAILABLE")
    value = None
