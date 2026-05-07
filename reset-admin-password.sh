#!/usr/bin/env bash
# Update ADMIN_PASSWORD on the live Cloud Run service without a full redeploy.
# The running container will use the new password on its next cold start; to
# force an immediate restart add --no-traffic / revise the revision.
#
# Usage:
#   ADMIN_PASSWORD=newpassword ./reset-admin-password.sh
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-medicaid-inspector}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="medicaid-inspector-api"

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: ADMIN_PASSWORD is not set."
  echo "  Usage: ADMIN_PASSWORD=newpassword ./reset-admin-password.sh"
  exit 1
fi

echo "==> Updating ADMIN_PASSWORD on Cloud Run service '${SERVICE_NAME}'..."
gcloud run services update "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "ADMIN_PASSWORD=${ADMIN_PASSWORD}"

echo "==> Done. A new revision will roll out shortly."
echo "    The admin account will use the new password on next container start."
echo "    To force an immediate restart, redeploy: ./deploy-backend.sh"
