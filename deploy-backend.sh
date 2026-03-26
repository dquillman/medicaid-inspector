#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-medicaid-inspector}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="medicaid-inspector-api"

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
  --set-env-vars "PYTHONUNBUFFERED=1"

echo "==> Backend deployed!"
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format "value(status.url)"
