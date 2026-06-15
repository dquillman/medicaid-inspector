#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-medicaid-inspector}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="medicaid-inspector-api"

# ADMIN_PASSWORD must be set so the admin account has a stable password across
# Cloud Run cold starts. Without it every new container generates a random
# one-time password that is only visible in the logs.
#
# Usage:
#   ADMIN_PASSWORD=yourpassword ./deploy-backend.sh
#
# Or store it in GCP Secret Manager and export before deploying:
#   gcloud secrets versions access latest --secret=admin-password --project=$PROJECT_ID
if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: ADMIN_PASSWORD is not set."
  echo "  Set it before deploying: ADMIN_PASSWORD=yourpassword ./deploy-backend.sh"
  echo "  Or retrieve from Secret Manager:"
  echo "    export ADMIN_PASSWORD=\$(gcloud secrets versions access latest --secret=admin-password --project=${PROJECT_ID})"
  exit 1
fi

# Single source of truth for the app version is frontend/package.json. Inject
# it so the backend (/health and the FastAPI docs) reports the same version as
# the UI instead of a hand-maintained constant that drifts.
APP_VERSION=$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' frontend/package.json | head -1)
APP_VERSION="${APP_VERSION:-dev}"
echo "==> App version: ${APP_VERSION}"

echo "==> Deploying backend to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --memory 2Gi \
  --cpu 1 \
  --max-instances 3 \
  --concurrency 80 \
  --timeout 300 \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars "PYTHONUNBUFFERED=1,ADMIN_PASSWORD=${ADMIN_PASSWORD},APP_VERSION=${APP_VERSION}"

echo "==> Backend deployed!"
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format "value(status.url)"
