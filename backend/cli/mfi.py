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
    nppes-enrich        Enrich cached providers from the NPPES registry
    news scan-hhs       Pull HHS-OIG RSS feed and add classified alerts
    news enrich-url     Classify a single press-release URL (prints JSON draft)
    user list           List configured users
    user reset-password Reset a user's password (generates one if omitted)
    train-ml            Retrain Isolation Forest on cached providers (Tier 2)
    feedback-summary    Print signal weight adjustments + dismissal stats (Tier 2)
    precompute-forecasts Pre-run forecaster for every provider in the cache (Tier 2)
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
# Default to the production project. Override with MFI_GCLOUD_PROJECT for
# staging / dev. Passing --project explicitly to gcloud means a stale
# `gcloud config set project ...` cannot redirect a deploy to the wrong
# project (which has happened once — see commit log).
_DEFAULT_GCLOUD_PROJECT = os.environ.get("MFI_GCLOUD_PROJECT", "medicaid-inspector")
_HEALTH_TIMEOUT_SECONDS = 60


# ── Helpers ──────────────────────────────────────────────────────────────────
def _log(msg: str) -> None:
    print(f"[mfi] {msg}", flush=True)


def _err(msg: str) -> int:
    print(f"[mfi] ERROR: {msg}", file=sys.stderr, flush=True)
    return 1


def _platform_exe(name: str) -> str:
    """Append `.cmd` on Windows so subprocess can find shell wrappers
    (npm, firebase, gcloud all ship as .cmd shims on Windows)."""
    if os.name == "nt" and not name.lower().endswith((".cmd", ".bat", ".exe")):
        return f"{name}.cmd"
    return name


def _run_shell(cmd: list[str], *, cwd: str | None = None, env: dict | None = None) -> int:
    """Run a subprocess command and stream output; return exit code."""
    _log(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, check=False)
        return result.returncode
    except FileNotFoundError as exc:
        # On Windows, FileNotFoundError.filename is often None for failed PATH
        # lookups — fall back to the cmd[0] so the error is actionable.
        missing = exc.filename or (cmd[0] if cmd else "unknown")
        return _err(f"command not found: {missing}")


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
    """Deploy backend to Cloud Run, then smoke-test /health.

    ADMIN_PASSWORD must be set on the deployed revision — otherwise each cold
    start picks a random one and locks everyone out (see deploy-backend.sh).
    We mount it as a Cloud Run secret via --update-secrets so the value
    never crosses the shell boundary or appears in logs.
    """
    repo_root = _BACKEND_DIR.parent
    secret_name = os.environ.get("MFI_ADMIN_PASSWORD_SECRET", "admin-password")

    # Single source of truth for the app version is frontend/package.json. Inject
    # it so /health and the FastAPI docs report the same version as the UI.
    # NOTE: gcloud's --set-env-vars REPLACES the whole env set, so APP_VERSION
    # must be listed here explicitly or the deployed revision reverts to "dev".
    app_version = "dev"
    try:
        _pkg = json.loads((repo_root / "frontend" / "package.json").read_text(encoding="utf-8"))
        app_version = _pkg.get("version") or "dev"
    except Exception:
        _log("WARNING: could not read frontend/package.json version — deploying APP_VERSION=dev")

    # gcloud's bundled `third_party/pyasn1` is corrupted in some Cloud SDK
    # installs (missing `pyasn1.type.univ`). Setting CLOUDSDK_PYTHON_SITEPACKAGES=1
    # lets gcloud fall back to the system Python's site-packages, where pyasn1
    # and cryptography are installable via pip. We only set these if the user
    # has not overridden them, and only if CLOUDSDK_PYTHON exists — never force
    # a broken Python on a known-good gcloud install.
    deploy_env = os.environ.copy()
    cloudsdk_python = os.environ.get("CLOUDSDK_PYTHON") or os.environ.get("MFI_GCLOUD_PYTHON")
    if cloudsdk_python:
        deploy_env.setdefault("CLOUDSDK_PYTHON", cloudsdk_python)
        deploy_env.setdefault("CLOUDSDK_PYTHON_SITEPACKAGES", "1")

    cmd = [
        _platform_exe("gcloud"), "run", "deploy", _DEFAULT_GCLOUD_SERVICE,
        "--source", str(repo_root),
        "--project", _DEFAULT_GCLOUD_PROJECT,
        "--region", _DEFAULT_GCLOUD_REGION,
        "--allow-unauthenticated",
        "--set-env-vars", f"PYTHONUNBUFFERED=1,APP_VERSION={app_version}",
        "--update-secrets", f"ADMIN_PASSWORD={secret_name}:latest",
        "--quiet",
    ]
    _log(f"deploying backend v{app_version} to {_DEFAULT_GCLOUD_SERVICE} …")
    rc = _run_shell(cmd, env=deploy_env)
    if rc != 0:
        return _err(
            f"gcloud run deploy failed with exit code {rc}. "
            f"If the failure mentions secret access, grant the Cloud Run service account "
            f"the 'Secret Manager Secret Accessor' role on the {secret_name!r} secret."
        )

    # Smoke test — confirm 200 AND that the deployed version matches what we
    # just built, catching the "APP_VERSION reverted / wrong image" failure mode.
    _log(f"smoke-testing {_DEFAULT_BACKEND_URL}/health …")
    deadline = time.time() + _HEALTH_TIMEOUT_SECONDS
    while time.time() < deadline:
        status, body = _http_get(f"{_DEFAULT_BACKEND_URL}/health", timeout=5.0)
        if status == 200:
            _log(f"health check passed: {body[:120]}")
            if f'"{app_version}"' not in body:
                _log(
                    f"WARNING: /health does not report v{app_version} — the deployed "
                    "revision may be serving a stale APP_VERSION or image."
                )
            return 0
        time.sleep(3)
    return _err("health check did not return 200 within timeout — investigate before traffic shifts")


def cmd_deploy_all(args: argparse.Namespace) -> int:
    """Deploy backend then frontend in the correct order.

    Frontend-only deploys ship UI that can break against an old API, and
    backend-only deploys leave the UI stale — so the safe default is to ship
    both. Backend goes first so the API is ready before the new UI reaches users.
    """
    _log("deploy all: backend first, then frontend")
    rc = cmd_deploy_backend(args)
    if rc != 0:
        return _err("backend deploy failed — aborting before frontend so the pair stays consistent")
    return cmd_deploy_frontend(args)


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
        rc = _run_shell([_platform_exe("npm"), "run", "build"], cwd=str(frontend_dir))
        if rc != 0:
            return _err(f"npm run build failed with exit code {rc}")

    rc = _run_shell([_platform_exe("firebase"), "deploy", "--only", "hosting"], cwd=str(frontend_dir))
    if rc != 0:
        return _err(f"firebase deploy failed with exit code {rc}")

    # Verify deployed bundle. Firebase/CDN propagation lags the deploy by a few
    # seconds, so an instant single check gives false "not found" negatives.
    # Retry, RE-FETCHING index.html each attempt (its bundle hash changes as the
    # new version propagates) with a cache-busting query so we don't read a
    # stale edge-cached copy. Only fail after all attempts miss.
    import re
    hosting_url = os.environ.get("MFI_HOSTING_URL", "https://medicaid-inspector.web.app")
    attempts, backoff = 5, 6.0
    _log(f"verifying deployed bundle at {hosting_url} … (up to {attempts} attempts)")
    last_reason = "verification did not run"
    for attempt in range(1, attempts + 1):
        cb = f"?_cb={int(time.time())}"  # cache-bust CDN edges
        status, body = _http_get(hosting_url + "/" + cb, timeout=10.0)
        if status != 200:
            last_reason = f"hosting returned status {status}"
        else:
            m = re.search(r'assets/(index-[A-Za-z0-9_-]+\.js)', body)
            if not m:
                last_reason = "could not locate bundle asset name in index.html"
            else:
                asset_path = m.group(0)
                status2, bundle = _http_get(f"{hosting_url}/{asset_path}{cb}", timeout=15.0)
                if status2 != 200:
                    last_reason = f"bundle fetch returned {status2}"
                elif declared_version and declared_version in bundle:
                    # Unquoted substring match: the minifier emits the injected
                    # __APP_VERSION__ as a template-literal fragment (`3.16.1`,
                    # backticks), so the old '"X.Y.Z"' double-quoted check could
                    # NEVER match — that, not CDN lag, was the recurring false
                    # "not found in deployed bundle" warning on every release.
                    _log(f"verified: bundle contains v{declared_version} (attempt {attempt})")
                    return 0
                else:
                    last_reason = f"declared version {declared_version!r} not found in deployed bundle"
        if attempt < attempts:
            _log(f"  not confirmed yet ({last_reason}); retrying in {backoff:.0f}s…")
            time.sleep(backoff)
    _log(f"WARNING: {last_reason} after {attempts} attempts")
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


# ── Subcommand: nppes-enrich ─────────────────────────────────────────────────
def cmd_nppes_enrich(args: argparse.Namespace) -> int:
    """Enrich providers in the prescan cache with NPPES registry data."""
    try:
        from core.store import load_prescanned_from_disk, get_prescanned
        from services.nppes_enricher import enrich_batch_with_nppes
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import nppes enricher: {exc}")

    load_prescanned_from_disk()
    providers = get_prescanned()
    if args.all:
        targets = [p["npi"] for p in providers]
    else:
        targets = [
            p["npi"] for p in providers
            if not p.get("nppes") or not (p.get("nppes") or {}).get("enumeration_date")
        ]

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        _log("nothing to enrich")
        return 0

    _log(f"enriching {len(targets)} providers from NPPES…")
    t0 = time.time()
    try:
        asyncio.run(enrich_batch_with_nppes(targets))
    except KeyboardInterrupt:
        return _err("interrupted")
    except Exception as exc:  # noqa: BLE001
        return _err(f"nppes enrichment failed: {exc}")
    _log(f"nppes enrichment complete in {time.time() - t0:.1f}s")
    return 0


# ── Subcommand: news ─────────────────────────────────────────────────────────
def cmd_news_scan_hhs(args: argparse.Namespace) -> int:
    """Pull HHS-OIG RSS feed and add classified alerts."""
    try:
        import httpx
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime
        from core.news_store import add_alert, load_news_from_disk
        from services.news_enrichment import classify_item
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import news modules: {exc}")

    load_news_from_disk()
    feed_url = "https://oig.hhs.gov/rss/enforcement.xml"
    _log(f"fetching {feed_url}…")
    try:
        resp = httpx.get(feed_url, timeout=15.0)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return _err(f"feed fetch failed: {exc}")

    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    items = (channel.findall("item") if channel is not None else root.findall("item")) or []

    added = 0
    for item in items[:50]:
        title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()
        summary = (item.findtext("description") or "").strip()
        pub = item.findtext("pubDate")
        date_str = None
        if pub:
            try:
                date_str = parsedate_to_datetime(pub).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                date_str = pub[:10] if len(pub) >= 10 else None

        classified = classify_item(title, summary)
        try:
            add_alert(
                title=title,
                source="HHS OIG",
                url=link,
                category=classified["category"],
                summary=classified["summary"],
                severity=classified["severity"],
                npi=classified["npi"],
                date=date_str,
            )
            added += 1
        except Exception as exc:  # noqa: BLE001
            _log(f"WARNING: failed to store alert {title!r}: {exc}")

    _log(f"added {added} alerts")
    return 0


def cmd_news_enrich_url(args: argparse.Namespace) -> int:
    """Classify a single press-release URL — prints a JSON draft alert."""
    try:
        import httpx
        import re as _re
        from services.news_enrichment import enrich_from_text
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import news_enrichment: {exc}")

    try:
        resp = httpx.get(args.url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return _err(f"URL fetch failed: {exc}")

    html = resp.text
    text = _re.sub(r"<script[\s\S]*?</script>", " ", html, flags=_re.I)
    text = _re.sub(r"<style[\s\S]*?</style>", " ", text, flags=_re.I)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
    title_match = _re.search(r"<title>([^<]+)</title>", html, flags=_re.I)
    title = title_match.group(1).strip() if title_match else text[:120]

    draft = enrich_from_text(
        title=title, source=args.source, url=args.url, summary=text[:2000]
    )
    print(json.dumps(draft, indent=2))
    return 0


# ── Subcommand: user ─────────────────────────────────────────────────────────
def cmd_user_list(args: argparse.Namespace) -> int:
    """List configured users."""
    try:
        from core.auth_store import init_auth_store, list_users
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import auth_store: {exc}")
    init_auth_store()
    for u in list_users():
        print(f"{u['username']:24s}  role={u['role']:8s}  name={u.get('display_name', '')}")
    return 0


def cmd_user_reset_password(args: argparse.Namespace) -> int:
    """Reset a user password — generates a strong one if --password is omitted."""
    try:
        from core.auth_store import init_auth_store, get_user, update_user
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import auth_store: {exc}")

    init_auth_store()
    if not get_user(args.user):
        return _err(f"user {args.user!r} not found")

    new_pw = args.password
    if not new_pw:
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits + "-_"
        new_pw = "".join(secrets.choice(alphabet) for _ in range(20))

    update_user(args.user, {"password": new_pw})
    _log(f"password reset for {args.user!r}")
    if not args.password:
        # Only echo if we generated it. If the caller supplied --password
        # they already have the value and we shouldn't print it.
        print(f"New password: {new_pw}")
    return 0


# ── Subcommand: train-ml ─────────────────────────────────────────────────────
def cmd_train_ml(args: argparse.Namespace) -> int:
    """Retrain Isolation Forest on every provider in the prescan cache.

    Moves training out of the hot request path — was previously called inline
    from ``POST /api/ml/train``, which blocked the worker for several seconds
    on a cold cache. Schedule this nightly via cron so the served model is
    always warm.
    """
    try:
        from core.store import load_prescanned_from_disk
        from services.ml_scorer import train_and_score
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import ml_scorer: {exc}")

    # Make sure the in-memory cache is populated when invoked outside the API.
    load_prescanned_from_disk()
    _log("training Isolation Forest on prescan cache…")
    t0 = time.time()
    try:
        result = train_and_score()
    except Exception as exc:  # noqa: BLE001
        return _err(f"ml training failed: {exc}")
    elapsed = time.time() - t0
    if "error" in result:
        return _err(f"{result['error']} (after {elapsed:.1f}s)")
    _log(f"ml training complete in {elapsed:.1f}s")
    print(json.dumps(result, indent=2, default=str))
    return 0


# ── Subcommand: feedback-summary ─────────────────────────────────────────────
def cmd_feedback_summary(args: argparse.Namespace) -> int:
    """Print the current weight adjustments and dismissal/confirmation counts.

    Useful for ops review: which signals are over-firing and quietly losing
    weight because investigators keep dismissing them.
    """
    try:
        from services.feedback_tracker import get_feedback_summary
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import feedback_tracker: {exc}")

    try:
        summary = get_feedback_summary()
    except Exception as exc:  # noqa: BLE001
        return _err(f"feedback summary failed: {exc}")

    print(json.dumps(summary, indent=2, default=str))
    return 0


# ── Subcommand: precompute-forecasts ─────────────────────────────────────────
def cmd_precompute_forecasts(args: argparse.Namespace) -> int:
    """Pre-run the forecaster against every cached provider; write a JSON cache.

    Removes a per-request linear regression from the hot path. The cache lands
    at ``backend/forecast_cache.json`` and is safe to delete — the next CLI
    run rebuilds it.
    """
    try:
        from core.store import load_prescanned_from_disk
        from services.forecaster import precompute_all_forecasts
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to import forecaster: {exc}")

    load_prescanned_from_disk()
    _log(f"precomputing forecasts (min_months={args.min_months})…")
    try:
        result = precompute_all_forecasts(min_months=args.min_months)
    except Exception as exc:  # noqa: BLE001
        return _err(f"precompute failed: {exc}")
    _log(
        f"wrote {result['forecasts_written']}/{result['providers_total']} "
        f"forecasts to {result['output_path']} in {result['elapsed_seconds']}s"
    )
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

    p_deploy_all = deploy_sub.add_parser(
        "all", help="Deploy backend then frontend (the safe default — keeps the pair in sync)")
    p_deploy_all.add_argument("--skip-build", action="store_true", help="Skip npm run build for the frontend step")
    p_deploy_all.set_defaults(func=cmd_deploy_all)

    # sync-exclusions
    p_sync = sub.add_parser("sync-exclusions", help="Refresh OIG + SAM + NPI exclusion data")
    p_sync.set_defaults(func=cmd_sync_exclusions)

    # nppes-enrich
    p_npp = sub.add_parser("nppes-enrich", help="Enrich cached providers from the NPPES registry")
    p_npp.add_argument("--all", action="store_true", help="Re-enrich every provider, not just those missing NPPES data")
    p_npp.add_argument("--limit", type=int, default=0, help="Cap number of providers to enrich (0 = no cap)")
    p_npp.set_defaults(func=cmd_nppes_enrich)

    # news
    p_news = sub.add_parser("news", help="News-alert ingestion")
    news_sub = p_news.add_subparsers(dest="news_cmd", required=True)
    p_news_hhs = news_sub.add_parser("scan-hhs", help="Pull HHS-OIG RSS and add classified alerts")
    p_news_hhs.set_defaults(func=cmd_news_scan_hhs)
    p_news_url = news_sub.add_parser("enrich-url", help="Classify a single press-release URL (prints JSON draft)")
    p_news_url.add_argument("url", help="URL of the press release to classify")
    p_news_url.add_argument("--source", default="Manual", help="Source name for the draft alert")
    p_news_url.set_defaults(func=cmd_news_enrich_url)

    # user
    p_user = sub.add_parser("user", help="User administration")
    user_sub = p_user.add_subparsers(dest="user_cmd", required=True)
    p_user_ls = user_sub.add_parser("list", help="List configured users")
    p_user_ls.set_defaults(func=cmd_user_list)
    p_user_rp = user_sub.add_parser("reset-password", help="Reset a user's password")
    p_user_rp.add_argument("--user", required=True, help="Username to reset")
    p_user_rp.add_argument("--password", default=None, help="New password (generated if omitted)")
    p_user_rp.set_defaults(func=cmd_user_reset_password)

    # train-ml
    p_train = sub.add_parser("train-ml", help="Retrain Isolation Forest on cached providers")
    p_train.set_defaults(func=cmd_train_ml)

    # feedback-summary
    p_feedback = sub.add_parser(
        "feedback-summary",
        help="Print signal weight adjustments + dismissal/confirmation counts",
    )
    p_feedback.set_defaults(func=cmd_feedback_summary)

    # precompute-forecasts
    p_pf = sub.add_parser(
        "precompute-forecasts",
        help="Pre-run forecaster for every provider; write forecast_cache.json",
    )
    p_pf.add_argument(
        "--min-months",
        type=int,
        default=3,
        help="Skip providers with fewer than N months of history (default: 3)",
    )
    p_pf.set_defaults(func=cmd_precompute_forecasts)

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
