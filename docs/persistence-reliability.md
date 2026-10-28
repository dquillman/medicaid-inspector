# Persistence guarantees and limits

State remains whole-file JSON/SQLite storage. Keep the deployment restricted to one instance. Generation preconditions prevent a stale instance from replacing a newer object, but they do not merge records, provide cross-file transactions, or provide rollback across local and cloud writes.

## What is enforced

- Startup downloads capture the exact GCS generation and use generation-matched downloads into temporary files before replacement. Failed/size-rejected downloads do not establish a writable remote baseline.
- Uploads use `if_generation_match` with the generation that this instance loaded or last successfully wrote. An unknown existing object is refused; a new object uses generation zero (create-only). Remote conflicts remain conflicts until an operator reconciles them. No blind retry adopts the newer generation.
- Byte uploads, including evidence metadata, use the same generation preconditions. New evidence objects cannot overwrite an unknown existing object.
- SQLite uploads use the online backup API into a temporary database, including committed WAL data, rather than copying an active database file. Upload snapshots and per-instance uploads are serialized.
- JSON writes flush and fsync the temporary file before atomic replacement. Locks protect threads within a process only. Filesystem/platform atomicity and power-loss behavior still depend on the host.
- Request-scoped persistence events propagate through async threadpool writes. A request with an observed sync failure returns HTTP 503 with an explicit warning that local changes may already exist and no rollback is implied. Deferred writes return HTTP 202 with `X-MFI-Persistence: pending`; confirmed writes expose `durable`. Requests without write events preserve their existing response. Unrelated background errors and download/read events do not contaminate acknowledgments. Callers outside HTTP requests and failures that never reach the sync layer remain outside this protection.
- `get_sync_status()` exposes per-object pending, synced, conflict, untracked, unavailable and error states to an admin integration. Deferred uploads are explicitly not durable acknowledgments. Error messages contain no file contents or credentials.

## Operational response

A conflict is a stop condition for that file, not a reason to force upload. Preserve both local and remote versions, compare their records and timestamps, reconcile deliberately, and restart from the reconciled remote state. Do not manually download over a live SQLite connection. Do not treat a background upload request or successful local save as cloud durability. The middleware propagates observed request-owned sync failures even when the caller catches them. It cannot establish durability for asynchronous work after the response, local failures never reported to the sync layer, or cross-file consistency. No blanket guarantee that every mutation survives a restart is asserted.

Before expanding beyond one instance, replace mutable whole-file state with record-level transactional storage and add concurrent-update/restore verification in a staging environment. This change does not provision that infrastructure, migrate state, contact GCS, restore backups, or prove production durability.

## Verification

Fake-object tests verify stale-generation rejection, unknown-object protection and status reporting. Disposable SQLite tests verify committed WAL content and database integrity in an uploaded snapshot. Serialization failure tests verify that an existing JSON file remains intact. These tests are offline and do not exercise real bucket IAM, network failure modes, GCS generation responses or deployment restarts. The restricted Windows sandbox denied a disposable atomic rename test and blocked asyncio socketpair setup; the source-only test runner was therefore also run outside that sandbox with external networking blocked. Synthetic middleware tests verify failed/pending/durable acknowledgments and separation from unrelated requests/background work. Real deployment and crash/power-loss verification remain pending.
