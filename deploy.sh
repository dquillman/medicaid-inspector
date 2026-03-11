#!/bin/bash
set -e

echo "=== Building frontend ==="
cd frontend
npm run build
cd ..

echo "=== Deploying to Cloud Run ==="
gcloud run deploy medicaid-inspector \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8000 \
  --memory 2Gi \
  --timeout 300

echo "=== Deploying Firebase Hosting ==="
firebase deploy --only hosting

echo "=== Done! ==="
