#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "  Medicaid Inspector — Full Deployment"
echo "========================================="

# Deploy backend first (Cloud Run)
bash deploy-backend.sh

# Deploy frontend (Firebase Hosting)
bash deploy-frontend.sh

echo ""
echo "========================================="
echo "  Deployment complete!"
echo "  Frontend: https://medicaid-inspector.web.app"
echo "  Backend:  (see Cloud Run URL above)"
echo "========================================="
