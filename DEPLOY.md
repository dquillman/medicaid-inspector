# Deployment Guide

## Prerequisites
- Node.js 18+ and npm
- Python 3.11+
- Firebase CLI: `npm install -g firebase-tools`
- Google Cloud SDK: https://cloud.google.com/sdk/install
- A Google Cloud project with billing enabled

## Initial Setup (One-Time)

### 1. Create Firebase Project
```bash
firebase login
firebase projects:create medicaid-inspector
firebase use medicaid-inspector
```

### 2. Configure Google Cloud
```bash
gcloud auth login
gcloud config set project medicaid-inspector
gcloud services enable run.googleapis.com cloudbuild.googleapis.com
```

### 3. Link Firebase Hosting to Cloud Run
The `firebase.json` file already configures rewrites from `/api/**` to the Cloud Run service `medicaid-inspector-api` in `us-central1`.

## Deploy

### Full Deploy (Backend + Frontend)
```bash
bash deploy.sh
```

### Frontend Only
```bash
bash deploy-frontend.sh
```

### Backend Only
```bash
bash deploy-backend.sh
```

## Data artifacts are NOT shipped by a code deploy

Several files are **GCS-synced state**, not code. `main.py`'s lifespan downloads
them from `gs://medicaid-inspector-data/` at startup and **overwrites whatever is
on disk** — locally as well as in prod. A code deploy does not update them, and
rebuilding one locally is undone by the next local backend restart.

Rebuild → upload → deploy, in that order:

```bash
cd backend
G:/Python311/python.exe -X utf8 scripts/build_deactivations.py   # NPPES -> deactivations + windows
G:/Python311/python.exe -X utf8 scripts/build_perse_sweep.py     # OIG + deactivations -> per-se leads
gsutil cp npi_deactivations.json npi_deactivation_windows.json perse_leads.json \
          gs://medicaid-inspector-data/
```

Skipping the upload leaves prod serving the previous sweep with no error — the
page still renders, just with stale counts. Observed 2026-07-26: a freshly built
9,313-entry `npi_deactivations.json` was silently replaced by the bucket's
1,025-entry copy on the next local restart.

`build_deactivations.py` needs the extracted NPPES bulk CSV at
`G:/temp/nppes_extract/` (produced by `scripts/backfill_nppes_bulk.py`).

## Architecture
- **Frontend**: Firebase Hosting serves the React SPA from `frontend/dist/`
- **Backend**: Cloud Run runs the FastAPI backend (2GB memory, auto-scaling 0-3 instances)
- **API Proxy**: Firebase Hosting rewrites `/api/**` requests to Cloud Run
- **Data**: DuckDB reads remote Parquet from Azure Blob Storage. Local JSON/SQLite storage is ephemeral (resets on redeploy).

## URLs
- Frontend: https://medicaid-inspector.web.app
- Backend API: https://medicaid-inspector-api-HASH-uc.a.run.app

## Environment Variables (Cloud Run)
- `PORT` -- Set automatically by Cloud Run (8080)
- `PYTHONUNBUFFERED` -- Set to 1 for log streaming

## Costs
- Firebase Hosting: Free tier covers most usage (10 GB storage, 360 MB/day transfer)
- Cloud Run: Free tier covers 2M requests/month, 360K vCPU-seconds, 180K GiB-seconds
- Cloud Build: 120 free build-minutes/day
