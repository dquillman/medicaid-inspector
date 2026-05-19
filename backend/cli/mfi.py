#!/usr/bin/env python3
"""
mfi — Medicaid Inspector command-line interface.

Wraps the most common operational workflows so they can be cron-scheduled
or invoked directly without going through the web UI.

Usage (from repo root):
    python -m backend.cli.mfi <subcommand> [options]
    # or use the mfi.bat / mfi shell wrapper

Subcommands:
    scan                Run a batch scan of providers
    rescore             Re-run all 17 fraud signals against cached providers
    backup create       Create a timestamped backup zip
    backup list         List existing backups
    backup restore <id> Restore from a backup id
    deploy backend      gcloud run deploy (with health check)
    deploy frontend     npm build + firebase deploy --only hosting
    sync-exclusions     Refresh OIG + SAM + NPI exclusion data
    version             Print version and exit

Exit codes:
    0 = success, 1 = error, 2 = bad arguments
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
from typing import Any

# ── Bootstrap import path ────────────────────────────────────────────────────
# This file lives at backend/cli/mfi.py. Add the backend dir to sys.path so the
# CLI can be run as `python backend/cli/mfi.py …` without installing a package.
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ── Defaults / config ────────────────────────────────────────────────────────
_DEFAULT_BACKEND_URL = os.environ.get(
    "MFI_BACKEND_URL",
    "https://medicaid-inspector-api-447172598773.us-central1.run.app",
)
_DEFAULT_GCLOUD_SERVICE = os.environ.get("MFI_GCLOUD_SERVICE", "medicaid-inspector-api")
_DEFAULT_GCLOUD_REGION = os.environ.get("MFI_GCLOUD_REGION", "us-central1")
_HEALTH_TIMEOUT_SECONDS = 60


# ── Helpers ──────────────────────────────────────────────────────────────────
def _log(msg: str) -> None:
    print(f"[mfi] {msg}", flush=True)


def _err(msg: str) -> int:
    print(f"[mfi] ERROR: {msg}", file=sys.stderr, flush=True)
    return 1


def _run_shell(cmd: list[str], *, cwd: str | None = None) -> int:
    """Run a subprocess command and stream output; return exit code."""
    _log(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd, check=False)
        return result.returncode
    except FileNotFoundError as exc:
        return _err(f"command not found: {exc.filename}")


def _http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Minimal stdlib HTTP GET. Returns (status, body)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mfi-cli/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


# ── Subcommand: scan ─────────────────────────────────────────────────────────
def cmd_scan(args: argparse.Namespace) -> int:
    """Run a batch scan synchronously."""
    try:
        from services.scan_engine import run_scan_batch
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import scan engine: {exc}")

    _log(f"starting scan: batch_size={args.batch_size}, state={args.state or 'all'}, force={args.force}")
    t0 = time.time()
    try:
        asyncio.run(run_scan_batch(args.batch_size, args.state, args.force))
    except KeyboardInterrupt:
        return _err("interrupted")
    except Exception as exc:  # noqa: BLE001
        return _err(f"scan failed: {exc}")
    _log(f"scan complete in {time.time() - t0:.1f}s")
    return 0


# ── Subcommand: rescore ──────────────────────────────────────────────────────
def cmd_rescore(args: argparse.Namespace) -> int:
    """Re-run all 17 fraud signals against the prescan cache."""
    try:
        from services.scan_engine import rescore_cached_providers
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import scan engine: {exc}")

    _log("rescoring cached providers…")
    t0 = time.time()
    try:
        result = asyncio.run(rescore_cached_providers())
    except KeyboardInterrupt:
        return _err("interrupted")
    except Exception as exc:  # noqa: BLE001
        return _err(f"rescore failed: {exc}")
    _log(f"rescore complete in {time.time() - t0:.1f}s: {json.dumps(result, default=str)}")
    return 0


# ── Subcommand: backup ───────────────────────────────────────────────────────
def cmd_backup(args: argparse.Namespace) -> int:
    """Manage backups (create / list / restore)."""
    try:
        from services import backup as backup_mod
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import backup module: {exc}")

    if args.action == "create":
        info = backup_mod.create_backup()
        _log(f"created {info['backup_id']} ({info['size_mb']} MB, {info['files_included']} files)")
        print(json.dumps(info, indent=2))
        return 0

    if args.action == "list":
        backups = backup_mod.list_backups()
        if not backups:
            _log("no backups found")
            return 0
        _log(f"{len(backups)} backup(s):")
        for b in backups:
            print(f"  {b['backup_id']}  {b['size_mb']:>7.2f} MB  {b['file_count']:>4} files  {b['created_at']}")
        return 0

    if args.action == "restore":
        if not args.backup_id:
            return _err("restore requires a backup_id")
        info = backup_mod.restore_backup(args.backup_id)
        if "error" in info:
            return _err(info["error"])
        _log(f"restored {info['restored_files']} file(s)")
        if info.get("skipped_unsafe"):
            _log(f"WARNING: skipped {len(info['skipped_unsafe'])} unsafe entries: {info['skipped_unsafe']}")
        print(json.dumps(info, indent=2, default=str))
        _log(info.get("note", ""))
        return 0

    return _err(f"unknown backup action: {args.action}")


# ── Subcommand: deploy ───────────────────────────────────────────────────────
def cmd_deploy_backend(args: argparse.Namespace) -> int:
    """Deploy backend to Cloud Run, then smoke-test /health."""
    repo_root = _BACKEND_DIR.parent
    cmd = [
        "gcloud", "run", "deploy", _DEFAULT_GCLOUD_SERVICE,
        "--source", str(repo_root),
        "--region", _DEFAULT_GCLOUD_REGION,
        "--allow-unauthenticated",
        "--quiet",
    ]
    rc = _run_shell(cmd)
    if rc != 0:
        return _err(f"gcloud run deploy failed with exit code {rc}")

    # Smoke test
    _log(f"smoke-testing {_DEFAULT_BACKEND_URL}/health …")
    deadline = time.time() + _HEALTH_TIMEOUT_SECONDS
    while time.time() < deadline:
        status, body = _http_get(f"{_DEFAULT_BACKEND_URL}/health", timeout=5.0)
        if status == 200:
            _log(f"health check passed: {body[:120]}")
            return 0
        time.sleep(3)
    return _err("health check did not return 200 within timeout — investigate before traffic shifts")


def cmd_deploy_frontend(args: argparse.Namespace) -> int:
    """Build frontend and deploy to Firebase Hosting, then verify bundle version."""
    repo_root = _BACKEND_DIR.parent
    frontend_dir = repo_root / "frontend"
    if not frontend_dir.exists():
        return _err(f"frontend dir not found at {frontend_dir}")

    # Read declared version up-front so we can verify it landed
    pkg = json.loads((frontend_dir / "package.json").read_text(encoding="utf-8"))
    declared_version = pkg.get("version", "")
    _log(f"declared frontend version: {declared_version}")

    if not args.skip_build:
        # npm.cmd on Windows, npm elsewhere
        npm = "npm.cmd" if os.name == "nt" else "npm"
        rc = _run_shell([npm, "run", "build"], cwd=str(frontend_dir))
        if rc != 0:
            return _err(f"npm run build failed with exit code {rc}")

    firebase = "firebase.cmd" if os.name == "nt" else "firebase"
    rc = _run_shell([firebase, "deploy", "--only", "hosting"], cwd=str(frontend_dir))
    if rc != 0:
        return _err(f"firebase deploy failed with exit code {rc}")

    # Verify deployed bundle
    hosting_url = os.environ.get("MFI_HOSTING_URL", "https://medicaid-inspector.web.app")
    _log(f"verifying deployed bundle at {hosting_url} …")
    status, body = _http_get(hosting_url + "/", timeout=10.0)
    if status != 200:
        _log(f"WARNING: hosting returned status {status} (body: {body[:120]})")
        return 0  # Deploy itself succeeded; verification couldn't run
    # Extract bundle asset hash from index.html
    import re
    m = re.search(r'assets/(index-[A-Za-z0-9_-]+\.js)', body)
    if not m:
        _log("WARNING: could not locate bundle asset name in index.html")
        return 0
    asset_path = m.group(0)
    status2, bundle = _http_get(f"{hosting_url}/{asset_path}", timeout=15.0)
    if status2 != 200:
        _log(f"WARNING: bundle fetch returned {status2}")
        return 0
    if declared_version and f'"{declared_version}"' in bundle:
        _log(f"verified: bundle contains v{declared_version}")
        return 0
    _log(f"WARNING: declared version {declared_version!r} not found in deployed bundle")
    return 1


# ── Subcommand: sync-exclusions ──────────────────────────────────────────────
def cmd_sync_exclusions(args: argparse.Namespace) -> int:
    """Refresh OIG + SAM + NPI exclusion data."""
    try:
        from core.exclusion_aggregator import run_batch_exclusion_scan
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import exclusion aggregator: {exc}")

    _log("running batch exclusion scan…")
    t0 = time.time()
    try:
        result = run_batch_exclusion_scan()
    except Exception as exc:  # noqa: BLE001
        return _err(f"exclusion scan failed: {exc}")
    _log(f"exclusion sync complete in {time.time() - t0:.1f}s")
    print(json.dumps(result, indent=2, default=str))
    return 0


# ── Subcommand: version ──────────────────────────────────────────────────────
def cmd_version(args: argparse.Namespace) -> int:
    repo_root = _BACKEND_DIR.parent
    pkg_path = repo_root / "frontend" / "package.json"
    try:
        version = json.loads(pkg_path.read_text(encoding="utf-8")).get("version", "?")
    except Exception:  # noqa: BLE001
        version = "?"
    print(f"mfi CLI — Medicaid Inspector v{version}")
    return 0


# ── Argument parsing ─────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mfi",
        description="Medicaid Inspector command-line tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Run a batch scan of providers")
    p_scan.add_argument("--batch-size", type=int, default=50, help="Providers per batch (default: 50)")
    p_scan.add_argument("--state", default=None, help="Two-letter state filter (e.g. CA)")
    p_scan.add_argument("--force", action="store_true", help="Re-scan providers already in cache")
    p_scan.set_defaults(func=cmd_scan)

    # rescore
    p_rescore = sub.add_parser("rescore", help="Re-run all 17 fraud signals against cached providers")
    p_rescore.set_defaults(func=cmd_rescore)

    # backup
    p_backup = sub.add_parser("backup", help="Backup operations (create / list / restore)")
    p_backup.add_argument("action", choices=["create", "list", "restore"], help="Backup action")
    p_backup.add_argument("backup_id", nargs="?", default=None, help="Backup id (for restore)")
    p_backup.set_defaults(func=cmd_backup)

    # deploy
    p_deploy = sub.add_parser("deploy", help="Deploy backend or frontend")
    deploy_sub = p_deploy.add_subparsers(dest="target", required=True)

    p_deploy_be = deploy_sub.add_parser("backend", help="Deploy backend to Cloud Run")
    p_deploy_be.set_defaults(func=cmd_deploy_backend)

    p_deploy_fe = deploy_sub.add_parser("frontend", help="Build and deploy frontend to Firebase Hosting")
    p_deploy_fe.add_argument("--skip-build", action="store_true", help="Skip npm run build (use existing dist/)")
    p_deploy_fe.set_defaults(func=cmd_deploy_frontend)

    # sync-exclusions
    p_sync = sub.add_parser("sync-exclusions", help="Refresh OIG + SAM + NPI exclusion data")
    p_sync.set_defaults(func=cmd_sync_exclusions)

    # version
    p_version = sub.add_parser("version", help="Print version and exit")
    p_version.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
