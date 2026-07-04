#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-medicaid-inspector}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="medicaid-inspector-api"
ADMIN_PASSWORD_SECRET="${MFI_ADMIN_PASSWORD_SECRET:-admin-password}"

# The admin account password is mounted from GCP Secret Manager (secret
# "admin-password") rather than passed as a plaintext env var. A plaintext
# --set-env-vars value is readable by anyone with run.services.get and lingers
# in shell history; the secret reference never crosses the shell boundary.
# The Cloud Run service account needs the "Secret Manager Secret Accessor" role
# on this secret (granted once via reset-admin-password.sh / setup).
#
# Usage:  ./deploy-backend.sh
# Rotate the password by adding a new secret version, not by editing this file.

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
  --set-env-vars "PYTHONUNBUFFERED=1,APP_VERSION=${APP_VERSION}" \
  --set-secrets "ADMIN_PASSWORD=${ADMIN_PASSWORD_SECRET}:latest"

echo "==> Backend deployed!"
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format "value(status.url)"
