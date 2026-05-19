"""
Operator CLI for Medicaid Inspector.

Wraps batch / admin operations that previously had to be invoked via
HTTP endpoints or ad-hoc shell scripts. Designed for:

  - cron / Cloud Scheduler -> Cloud Run Jobs (containerized batch)
  - one-off ops from a developer shell
  - scripted rotation (password resets, backups) in CI

Run from the backend directory:

    python -m cli --help
    python -m cli scan batch --batch-size 200 --state TX
    python -m cli scan smart
    python -m cli ingest nppes --missing-only
    python -m cli admin reset-password --user admin
    python -m cli admin backup
    python -m cli news scan-hhs
    python -m cli news enrich-url https://oig.hhs.gov/...

All commands return non-zero on failure so they slot cleanly into
Cloud Run Jobs and shell pipelines.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import string
import sys
from typing import Optional

log = logging.getLogger("medicaid_inspector.cli")


# ── Shared bootstrap ─────────────────────────────────────────────────────────

def _bootstrap():
    """Mirror the startup-time loads that main.py does so services work standalone."""
    from core.store import load_prescanned_from_disk
    from core.review_store import load_review_from_disk
    from core.news_store import load_news_from_disk
    from core.alert_store import load_rules_from_disk
    from core.audit_log import load_audit_from_disk
    from core.watchlist_store import load_watchlist_from_disk
    from core.score_history import load_history_from_disk

    load_prescanned_from_disk()
    load_review_from_disk()
    load_news_from_disk()
    load_rules_from_disk()
    load_audit_from_disk()
    load_watchlist_from_disk()
    load_history_from_disk()


# ── scan ────────────────────────────────────────────────────────────────────

async def _cmd_scan_batch(args: argparse.Namespace) -> int:
    from services.scan_engine import run_scan_batch
    from core.scan_lock import acquire_scan_lock, release_scan_lock
    if not acquire_scan_lock():
        print("ERROR: scan already running (lock held)", file=sys.stderr)
        return 2
    try:
        await run_scan_batch(args.batch_size, args.state, force=args.force)
    finally:
        release_scan_lock()
    return 0


async def _cmd_scan_smart(args: argparse.Namespace) -> int:
    from services.scan_engine import run_smart_scan
    from core.scan_lock import acquire_scan_lock, release_scan_lock
    if not acquire_scan_lock():
        print("ERROR: scan already running (lock held)", file=sys.stderr)
        return 2
    try:
        await run_smart_scan(args.state)
    finally:
        release_scan_lock()
    return 0


async def _cmd_scan_rescore(_args: argparse.Namespace) -> int:
    from services.scan_engine import rescore_cached_providers
    await rescore_cached_providers()
    return 0


# ── ingest ──────────────────────────────────────────────────────────────────

async def _cmd_ingest_nppes(args: argparse.Namespace) -> int:
    """Enrich providers in the prescan cache with NPPES registry data."""
    from core.store import get_prescanned
    from services.nppes_enricher import enrich_batch_with_nppes

    providers = get_prescanned()
    if args.missing_only:
        targets = [
            p["npi"] for p in providers
            if not p.get("nppes") or not (p.get("nppes") or {}).get("enumeration_date")
        ]
    else:
        targets = [p["npi"] for p in providers]

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("Nothing to enrich.")
        return 0

    print(f"Enriching {len(targets)} providers via NPPES...")
    await enrich_batch_with_nppes(targets)
    print("Done.")
    return 0


def _cmd_ingest_oig(_args: argparse.Namespace) -> int:
    """Download the latest OIG exclusion list."""
    from core.oig_store import download_oig_list
    print("Downloading OIG exclusion list...")
    download_oig_list()
    print("Done.")
    return 0


# ── admin ───────────────────────────────────────────────────────────────────

def _gen_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _cmd_admin_reset_password(args: argparse.Namespace) -> int:
    from core.auth_store import update_user, get_user, init_auth_store

    init_auth_store()
    if not get_user(args.user):
        print(f"ERROR: user {args.user!r} not found", file=sys.stderr)
        return 1

    new_pw = args.password or _gen_password()
    update_user(args.user, {"password": new_pw})
    print(f"Password reset for user {args.user!r}")
    if not args.password:
        # Only print when we generated it. If the caller passed --password,
        # they already have the value and we shouldn't echo it.
        print(f"New password: {new_pw}")
    return 0


def _cmd_admin_backup(_args: argparse.Namespace) -> int:
    from services.backup import create_backup
    meta = create_backup()
    print(json.dumps(meta, indent=2, default=str))
    return 0


def _cmd_admin_list_users(_args: argparse.Namespace) -> int:
    from core.auth_store import list_users, init_auth_store
    init_auth_store()
    for u in list_users():
        print(f"{u['username']:24s}  role={u['role']:8s}  name={u.get('display_name', '')}")
    return 0


# ── news ────────────────────────────────────────────────────────────────────

async def _cmd_news_scan_hhs(_args: argparse.Namespace) -> int:
    """Fetch HHS-OIG RSS feed and add classified alerts."""
    import httpx
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    from core.news_store import add_alert
    from services.news_enrichment import classify_item

    feed_url = "https://oig.hhs.gov/rss/enforcement.xml"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()

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
            except Exception:
                date_str = pub[:10] if len(pub) >= 10 else None

        c = classify_item(title, summary)
        try:
            add_alert(
                title=title,
                source="HHS OIG",
                url=link,
                category=c["category"],
                summary=c["summary"],
                severity=c["severity"],
                npi=c["npi"],
                date=date_str,
            )
            added += 1
        except Exception as e:
            log.warning("Failed to store alert %r: %s", title, e)

    print(f"Added {added} alerts.")
    return 0


def _cmd_news_enrich_url(args: argparse.Namespace) -> int:
    import httpx, re as _re
    from services.news_enrichment import enrich_from_text

    resp = httpx.get(args.url, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
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


# ── parser ──────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="medicaid-inspector",
        description="Operator CLI for batch scans, ingestion, and admin tasks.",
    )
    sub = p.add_subparsers(dest="group", required=True)

    # scan group
    g_scan = sub.add_parser("scan", help="Run fraud-detection scans").add_subparsers(dest="cmd", required=True)
    p_batch = g_scan.add_parser("batch", help="Run one batch over unscored providers")
    p_batch.add_argument("--batch-size", type=int, default=100)
    p_batch.add_argument("--state", default=None, help="2-letter state filter (e.g. TX)")
    p_batch.add_argument("--force", action="store_true", help="Re-score already-scored providers")
    p_batch.set_defaults(func=_cmd_scan_batch, is_async=True)

    p_smart = g_scan.add_parser("smart", help="Run smart scan (prioritized rescore)")
    p_smart.add_argument("--state", default=None)
    p_smart.set_defaults(func=_cmd_scan_smart, is_async=True)

    p_resc = g_scan.add_parser("rescore", help="Re-score all currently cached providers")
    p_resc.set_defaults(func=_cmd_scan_rescore, is_async=True)

    # ingest group
    g_ing = sub.add_parser("ingest", help="Pull / refresh external data").add_subparsers(dest="cmd", required=True)
    p_npp = g_ing.add_parser("nppes", help="Enrich providers from NPPES registry")
    p_npp.add_argument("--missing-only", action="store_true", default=True)
    p_npp.add_argument("--all", dest="missing_only", action="store_false")
    p_npp.add_argument("--limit", type=int, default=0)
    p_npp.set_defaults(func=_cmd_ingest_nppes, is_async=True)

    p_oig = g_ing.add_parser("oig", help="Download latest OIG exclusion list")
    p_oig.set_defaults(func=_cmd_ingest_oig, is_async=False)

    # admin group
    g_adm = sub.add_parser("admin", help="Operational admin tasks").add_subparsers(dest="cmd", required=True)
    p_rst = g_adm.add_parser("reset-password", help="Reset a user password (generates one if not provided)")
    p_rst.add_argument("--user", required=True)
    p_rst.add_argument("--password", default=None, help="Optional — generated if omitted")
    p_rst.set_defaults(func=_cmd_admin_reset_password, is_async=False)

    p_bak = g_adm.add_parser("backup", help="Snapshot persistent state to a backup archive")
    p_bak.set_defaults(func=_cmd_admin_backup, is_async=False)

    p_lst = g_adm.add_parser("list-users", help="List configured users")
    p_lst.set_defaults(func=_cmd_admin_list_users, is_async=False)

    # news group
    g_news = sub.add_parser("news", help="News-alert ingestion").add_subparsers(dest="cmd", required=True)
    p_hhs = g_news.add_parser("scan-hhs", help="Pull HHS-OIG RSS and add classified alerts")
    p_hhs.set_defaults(func=_cmd_news_scan_hhs, is_async=True)

    p_enu = g_news.add_parser("enrich-url", help="Classify a single press-release URL (prints JSON)")
    p_enu.add_argument("url")
    p_enu.add_argument("--source", default="Manual")
    p_enu.set_defaults(func=_cmd_news_enrich_url, is_async=False)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    parser = _build_parser()
    args = parser.parse_args(argv)
    _bootstrap()
    if getattr(args, "is_async", False):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
