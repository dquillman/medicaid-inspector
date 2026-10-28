# Prepared hosted backend build context

Prepared locally on 2026-10-27 at `backend/.tmp/hosted-build-context-20261027`.

- 192 allowlisted inputs, 3,708,176 bytes copied (about 3.54 MiB).
- Canonical backend-only Dockerfile, backend requirements and Python application packages.
- Only two operational-format JSON inputs: public OIG exclusions and NPI deactivation reference stores.
- No users, sessions, app.db, cases, evidence, referrals, private evaluation material, credentials, environment files, datasets, logs, tests or previous staging snapshots.
- SHA-256 file inventory in `build-context-manifest.json`; preparation does not imply a successful container build.
- No frontend build, container build, network request, upload, resource provisioning or deployment was performed.

**Not yet ready for raw-data tests:** no local Parquet fixture is included. The current loader requires a valid local fixture larger than 1 MB or it falls back to its configured URL. Provisioning fresh staging credentials/bucket/service and setting the staging-only environment remain separate steps. Do not substitute the production dataset/bucket/service merely to make a missing-fixture test pass.

The context is a point-in-time source snapshot. If source changes, prepare a new output directory and review its manifest; the preparer refuses to overwrite existing directories.

```powershell
& G:\Python311\python.exe backend/scripts/prepare_hosted_build_context.py --source-root 'G:\Users\daveq\medicaid inspector' --output 'G:\Users\daveq\medicaid inspector\backend\.tmp\NEW-staging-build-context'
```

The preparer enforces a new output under the selected source's `backend/.tmp`, rejects out-of-tree required inputs, prunes hidden/private/test directories, and bounds total copied input to 32 MiB. It never invokes a build tool or cloud CLI. Synthetic tests verify exclusions, output guards, required reference inputs and manifest hashes.
