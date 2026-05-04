# Medicaid Inspector

Production fraud-detection platform for Medicaid provider data. Scans 100k+ providers and flags billing irregularities, shell-entity networks, and phantom-billing patterns using statistical anomaly detection and rule-based signals.

**Live:** [https://medicaid-inspector.web.app](https://medicaid-inspector.web.app)

---

## What it does

Ingests Medicaid claims data, scores every provider on six independent fraud signals, and surfaces a ranked review queue for investigators.

| Signal | What it catches |
| :---- | :---- |
| `claims_per_bene_anomaly` | Providers billing \>3σ above their specialty peer mean |
| `bene_concentration` | Excessive claims-per-beneficiary (phantom-billing pattern) |
| `upcoding_pattern` | A single high-reimbursement code dominating a provider's mix |
| `address_cluster_risk` | Many providers sharing one address (OIG co-location flag) |
| `corporate_shell_risk` | One authorized official controlling many NPIs (shell network) |
| `oig_exclusion` | Cross-reference against the federal OIG exclusion list |

Each provider receives a weighted composite risk score. Analysts work the queue top-down.

---

## Stack

- **Backend** — Python 3.11, FastAPI, DuckDB querying remote Parquet on Azure Blob Storage  
- **Frontend** — React \+ TypeScript \+ Vite \+ Tailwind  
- **Infra** — Google Cloud Run (auto-scaling 0–3 instances, 2 GB), Firebase Hosting, Cloud Build CI/CD  
- **Data scale** — 106,660 providers, multi-year claims history (2018–present)

---

## Architecture highlights

- Modular service layer: `core/`, `routes/`, `services/`, `tests/`  
- **HIPAA-aware audit logging** — every PHI access recorded in `phi_access_log.json`  
- **Configurable rules engine** — `alert_rules.json` and `watchlist.json` editable without redeploy  
- Rate limiting \+ role-based auth (admin / analyst / user)  
- Stateless backend; claims data is never persisted locally  
- API gateway: Firebase Hosting rewrites `/api/**` to Cloud Run

---

## Running locally

\# Backend

cd backend

pip install \-r requirements.txt

uvicorn main:app \--reload \--port 8000

\# Frontend

cd frontend

npm install

npm run dev

Production deployment instructions in [`DEPLOY.md`](http://./DEPLOY.md).

---

## Status

Active. Used as a reference implementation for fraud-detection workflows on government claims data.  
