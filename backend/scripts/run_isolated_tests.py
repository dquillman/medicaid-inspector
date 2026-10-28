"""Run tests from a source-only temporary checkout, never beside operator data.

Usage: python backend/scripts/run_isolated_tests.py [pytest arguments]
No .env, credentials, JSON state, Parquet, or evidence files are copied.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="mfi-isolated-tests-") as directory:
        target = Path(directory) / "backend"
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            if any(part in {"__pycache__", ".pytest_cache", ".venv", "node_modules", ".tmp", "private_evaluations", "private_validations"} for part in relative.parts):
                continue
            if path.is_file() and (path.suffix == ".py" or
                                   (relative.parts[0] == "tests" and path.suffix in {".json", ".csv", ".txt"})):
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
        env = dict(os.environ)
        for key in list(env):
            if any(term in key for term in ("API_KEY", "HAL_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS", "SMTP_PASS")):
                env.pop(key, None)
        env.update(GCS_BUCKET="", MFI_DISABLE_BACKGROUND_JOBS="1", MFI_OFFLINE_TESTS="1",
                   MFI_ISOLATED_SOURCE_ROOT=str(target.resolve()),
                   PYTHONDONTWRITEBYTECODE="1", LOCAL_PARQUET_PATH="", HAL_QCODE_DIR="",
                   HAL_TOKEN="", NARRATIVE_LLM_ENABLED="false")
        return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *(sys.argv[1:] or ["tests", "-q"])],
                              cwd=target, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
