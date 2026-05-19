# mfi — Medicaid Inspector CLI

A thin command-line interface that wraps the most common operational workflows
so they can run on a schedule (cron, Task Scheduler) or be invoked directly
without going through the web UI.

## Quick start

```bash
# From the repo root:
./mfi version
./mfi scan --batch-size 50 --state CA
./mfi rescore
./mfi backup create
./mfi backup list
./mfi backup restore backup_20260519_143022
./mfi sync-exclusions
./mfi nppes-enrich                          # fill in missing NPPES data
./mfi nppes-enrich --all --limit 5000       # re-enrich the first 5000
./mfi news scan-hhs                         # OIG RSS -> classified alerts
./mfi news enrich-url https://oig.hhs.gov/...
./mfi user list
./mfi user reset-password --user admin      # generates a strong password
./mfi deploy backend
./mfi deploy frontend
```

On Windows, use `mfi.bat` (created at repo root) instead of `./mfi`.

## Configuration

The CLI reads a few environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MFI_BACKEND_URL` | `https://medicaid-inspector-api-447172598773.us-central1.run.app` | Used for the post-deploy health check. |
| `MFI_HOSTING_URL` | `https://medicaid-inspector.web.app` | Used to verify the deployed frontend bundle version. |
| `MFI_GCLOUD_SERVICE` | `medicaid-inspector-api` | Cloud Run service name for `deploy backend`. |
| `MFI_GCLOUD_REGION` | `us-central1` | Cloud Run region. |
| `MFI_ADMIN_PASSWORD_SECRET` | `admin-password` | Secret Manager secret mounted as `ADMIN_PASSWORD` on the deployed revision. |
| `NEWS_LLM_ENABLED` | unset | When `true` (and `ANTHROPIC_API_KEY` is set), `news scan-hhs` and `news enrich-url` use Claude for classification. Falls back to keyword heuristics otherwise. |
| `NARRATIVE_LLM_ENABLED` + `ANTHROPIC_BAA_ACK` | unset | Both required to enable LLM enrichment of provider narratives. Routes still serve the template version when off. PHI guardrail — do not flip without a BAA. |

## Suggested cron / Task Scheduler entries

```cron
# Nightly scan (2 AM)
0 2 * * *  cd /path/to/repo && ./mfi scan --batch-size 100 >> logs/mfi-scan.log 2>&1

# Hourly exclusion refresh
15 * * * * cd /path/to/repo && ./mfi sync-exclusions >> logs/mfi-exclusions.log 2>&1

# Daily backup (1 AM, before scan)
0 1 * * *  cd /path/to/repo && ./mfi backup create >> logs/mfi-backup.log 2>&1

# Hourly news ingest (pull HHS OIG enforcement RSS)
30 * * * * cd /path/to/repo && ./mfi news scan-hhs >> logs/mfi-news.log 2>&1

# Weekly NPPES enrichment for any new providers (Sunday 3 AM)
0 3 * * 0  cd /path/to/repo && ./mfi nppes-enrich >> logs/mfi-nppes.log 2>&1
```

## Architecture

```
backend/cli/
  __init__.py          (package marker)
  mfi.py               (single-file CLI with argparse subcommands)
  README.md            (this file)

mfi                    (POSIX wrapper at repo root)
mfi.bat                (Windows wrapper at repo root)
```

Each subcommand imports the live backend service module (`services.scan_engine`,
`services.backup`, `core.exclusion_aggregator`) and invokes the same code paths
the FastAPI endpoints use. This means anything that works in the UI works in
the CLI and vice versa — no parallel code to maintain.

`deploy backend` and `deploy frontend` shell out to `gcloud` and `firebase`
respectively. They are not Python wrappers around those tools — they just
sequence the canonical commands plus a smoke-test step.

## Exit codes

* `0` — success
* `1` — runtime error (failed scan, failed deploy, health check failed)
* `2` — bad arguments (argparse default)
