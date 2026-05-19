---
name: deploy
description: Deploy the Medicaid Inspector backend and/or frontend to production. Use this skill when the user asks to "deploy", "ship", "push to prod", or "release" the app. Handles secret retrieval from GCP Secret Manager, runs the right gcloud / firebase commands, and verifies the deployed service is healthy. Do not run this on unrelated repos.
---

# Deploy Medicaid Inspector

This skill is a wrapper around the loose deploy scripts in this repo
(`deploy.sh`, `deploy-backend.sh`, `deploy-frontend.sh`) plus the steps
that operators currently do by hand: pulling `ADMIN_PASSWORD` out of
Secret Manager, sanity-checking the build, running the deploy, and
verifying the new revision answers `/health`.

## When to use

Invoke when the user says any of:

- "deploy" / "ship it" / "push to prod" / "release v..."
- "deploy the backend" / "deploy the frontend" / "deploy everything"
- "roll back" (see Rollback section)

If the user just wants to *build* (no deploy), don't run the deploy
commands — point them at `docker build` or `npm run build` instead.

## Preflight

Before running anything, confirm all of these. If any fails, stop and
tell the user — do not try to guess fixes.

1. `git status` is clean. Deploying uncommitted changes is almost
   always a mistake.
2. We're on the branch the user intends to deploy from (usually
   `main`). Ask if not sure.
3. `gcloud` is authenticated:
   `gcloud auth list --filter=status:ACTIVE --format="value(account)"`
   should return a non-empty result.
4. The `medicaid-inspector` GCP project is selected, or pass
   `--project medicaid-inspector` to every command (the scripts already do).
5. For frontend deploys: `firebase` CLI is installed and authenticated.

## Backend deploy (Cloud Run)

The hand-rolled script (`deploy-backend.sh`) requires `ADMIN_PASSWORD`
to be exported, otherwise Cloud Run cold starts generate a throwaway
random password and lock everyone out. **Always fetch it from Secret
Manager — never prompt the user to type it.**

```bash
export ADMIN_PASSWORD="$(gcloud secrets versions access latest \
  --secret=admin-password \
  --project=medicaid-inspector)"

./deploy-backend.sh
```

After the script finishes, **verify**:

```bash
SERVICE_URL="$(gcloud run services describe medicaid-inspector-api \
  --project medicaid-inspector --region us-central1 \
  --format 'value(status.url)')"

# Health probe — should return HTTP 200
curl -fsSL "$SERVICE_URL/health" || echo "HEALTH CHECK FAILED"

# Read the last 50 log lines to make sure startup didn't crash
gcloud run services logs read medicaid-inspector-api \
  --project medicaid-inspector --region us-central1 --limit 50
```

If the health check fails or the logs show a stack trace on startup,
tell the user immediately — do not "keep trying".

## Frontend deploy (Firebase Hosting)

```bash
./deploy-frontend.sh
```

This builds `frontend/` and pushes it to Firebase Hosting. After it
completes, fetch the hosting URL from `firebase.json` (channel: live)
and curl it to confirm a non-empty HTML response.

## Full deploy

`./deploy.sh` runs backend then frontend. Use it when the user asks
for "everything" or when both have changed since the last release.

## Rollback

Cloud Run keeps revisions. To roll the backend back:

```bash
# List recent revisions
gcloud run revisions list \
  --service medicaid-inspector-api \
  --project medicaid-inspector --region us-central1 \
  --limit 5

# Route 100% of traffic back to the previous revision
gcloud run services update-traffic medicaid-inspector-api \
  --project medicaid-inspector --region us-central1 \
  --to-revisions <REVISION_NAME>=100
```

For frontend rollback, use the Firebase Hosting console — there is no
clean CLI command for "promote the prior release", and getting it
wrong loses the current build. Ask the user to do it via the console
unless they explicitly insist on CLI.

## What this skill does NOT do

- It does not run tests. Run them separately before invoking deploy.
- It does not bump version numbers or tag releases. The user owns
  those decisions.
- It does not deploy to staging — there is no staging environment in
  this repo. Production deploys go straight to live.
- It does not touch Secret Manager values. Reading is fine; writing
  needs explicit user approval.

## After deploy

Always end with a one-line summary the user can paste into Slack:

> Deployed `medicaid-inspector-api` revision `<rev>` and frontend at
> `<commit-sha>`. Health check: green.
