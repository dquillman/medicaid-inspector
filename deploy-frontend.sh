#!/usr/bin/env bash
set -euo pipefail

echo "==> Building frontend..."
cd frontend
npm run build
cd ..

echo "==> Deploying to Firebase Hosting..."
firebase deploy --only hosting

echo "==> Frontend deployed!"
