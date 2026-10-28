# Synthetic backup/recovery verification — 2026-10-27

Executed the source-only isolated runner outside the restricted Windows sandbox with external networking blocked:

`G:/Python311/python.exe backend/scripts/run_isolated_tests.py tests/test_backup_recovery.py -q --tb=short`

Result: **4 passed**, one existing Pydantic deprecation warning. No production application startup, operator records, real provider identifiers, cloud uploads/downloads or production restore were involved. The temporary synthetic backend was removed by test cleanup; no recovered operator data is claimed.

## Verified exercise

The fixture creates every file in the shared GCS state inventory plus retained legacy/local cache inventory. This includes SQLite, review queue, referrals, OIG tips, evidence custody metadata and feedback. Non-database fixture files contain synthetic JSON or bytes, even when their names use a parquet suffix; this exercises custody, inventory and restoration, not real dataset validity.

An open SQLite database uses WAL mode and commits a fixture custody row. Backup takes an online SQLite snapshot while that connection remains open. A local evidence file and matching metadata are included. The fixture then closes SQLite, deliberately changes every backed-up state file, restores the archive and verifies SHA-256 equality for every restored member against the archive manifest. Restored SQLite passes `PRAGMA integrity_check` and contains the committed WAL row.

Additional tests verify that corrupted archive bytes fail hash validation before any state replacement, remote-only evidence references are explicitly reported as missing from the local archive, and path-traversing backup identifiers are rejected.

## Implemented controls

Backup inventory derives from the same state-file inventory as GCS synchronization, retaining additional local caches. Archives contain size/hash manifests and distinguish missing optional inventory files from uncached evidence references. Microsecond identifiers avoid collisions from backups created in the same second. Snapshot hashing and zip extraction stream data rather than loading the full provider cache into memory.

Restore validates complete inventory, authorized paths, hashes and SQLite integrity before replacing operator files. It refuses a live application SQLite connection or remaining WAL/SHM sidecars. New archives use atomic per-file replacement. Legacy archives without manifests require offline inspection rather than an unverified automated restore. Server restart is required to reload memory after a real maintenance restore.

## Remaining limits

This was a local synthetic recovery exercise, not a cloud recovery or staging deployment test. Cloud evidence objects that are absent from the local evidence cache are not silently fetched or included; such archives explicitly report they are not self-contained. Actual cloud recovery requires authorized bucket/object inventory and restore verification.

The service must quiesce mutations for cross-file consistency. Per-file snapshots and replacements are not a cross-file transaction; a process failure during restoration can leave a partially restored set. Retain the pre-restore state and perform operator-controlled reconciliation/restart. The exercise does not establish real bucket IAM, object retention, deployment restart recovery, recovery-time objectives, or data-source correctness.
