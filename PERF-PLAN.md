# MFI backend latency plan — batch the fan-out, cache the analytics scans

> **Status:** Plan only. No code changed. Authored from a read-only investigation
> (three mapping agents + direct reads of the cache/store/scan layers).
> **Execute this from a session rooted in `G:\Users\daveq\medicaid inspector` with the
> backend venv active** — not from another repo. Re-confirm exact line numbers before
> editing (they can drift).
>
> **Goal (verbatim):** "React render was never the main driver of perceived slowness —
> backend DuckDB data-fetch latency is. Tackle it by batching the per-row query fan-out
> and caching the analytics-endpoint scans."

## Diagnosis — what's slow, and what is already optimized

Most of the backend is already well-optimized, so this is a narrow, high-leverage plan.

**Already batched — DO NOT redo:**
- Scan pipeline issues 3–4 grouped `WHERE NPI IN (...)` queries per batch, not per provider — `services/scan_engine.py:288-324`.
- Rescore bulk-loads MUP in one join instead of 106k per-NPI lookups — `services/scan_engine.py:462-504`.
- Timelines-batch endpoint, network ego-graph (single `MATERIALIZED` CTE), NPPES/license enrichment (semaphore-bounded `gather`) — all already single-scan / concurrency-capped.

**Already fast — served from the in-memory prescan cache, no DuckDB:**
- Provider list/detail core, `states/heatmap`, all `geography/*`, `specialty/*`, `anomalies/*`, `demographics/*`. (Verified: these call `get_prescanned()`, never the Parquet.)

**The real latency** is the **per-NPI analytics panels on the provider-detail page** (Network, Temporal, Diagnoses, Related) and **per-code billing analytics** — each does a full remote-Parquet scan (15–60s; 503/504 on Cloud Run), and they all share one undersized 256-entry query cache that they thrash. That is the "pages feel instant" gap: the detail page's core loads instantly from cache, but its sub-panels each fire a cold full scan.

Root of the caching problem: one shared `TTLCache(maxsize=256, ttl=3600)` keyed by exact SQL — `core/cache.py:8`. Per-NPI queries (~100k distinct keys) and per-code queries (~5k) blow through 256 slots and evict each other and the whole-dataset aggregates.

---

## Part A — Batch the per-row query fan-out

### A1 (HIGH, contained) — collapse `related.py`'s 3 full scans into one CTE
`GET /api/providers/{npi}/related` runs three separate full-Parquet scans concurrently
(shared-billing / shared-servicing / shared-beneficiary) — `routes/related.py:138-142`.
Rewrite as one query over a single `MATERIALIZED` base scan with three CTEs
(pattern proven in `routes/network.py`). ~3× less I/O, one cache entry instead of three.

**⚠️ Correctness hazard — must handle before merging:** the shared-beneficiary CTE keys on
`BENE_ID`, **which does not exist in the current HHS spending dataset** (columns are
`BILLING_PROVIDER_NPI_NUM / SERVICING_PROVIDER_NPI_NUM / HCPCS_CODE / CLAIM_FROM_MONTH /
TOTAL_PAID / TOTAL_CLAIMS / TOTAL_UNIQUE_BENEFICIARIES`). Today the code survives only
because the three scans run in a `try/except` that gracefully drops the beneficiary scan
when it errors (`related.py:143-153`). A naive single-CTE merge turns that graceful
degradation into a hard 500. Either keep the beneficiary scan separate, or detect column
presence first (`DESCRIBE`) and include the bene CTE only when `BENE_ID` exists.

- Effort: ~0.5 day. Risk: low–medium (SQL correctness — verify against a synthetic fixture).

### A2 (LOW / mostly latent) — batch the provider-list DuckDB fallback
When the prescan cache is empty, `routes/providers.py:974-978` loops
`for row in rows: await score_provider(...)`, and each `score_provider` fires 3 per-NPI
scans (`services/risk_scorer.py:41-50`) → 3×N scans per page. Replace with the
`WHERE NPI IN (page)` grouped shape the scan engine already uses.
**Deprioritized because:** in production this path is guarded — remote-Parquet fallbacks
fail fast (`providers.py:955-961`) — so it only bites local/self-hosted deploys with an
empty cache. **Also: `providers.py` currently has uncommitted WIP — coordinate before editing.**

**Out of scope:** re-batching the scan engine — already O(1) per batch.

---

## Part B — Cache the analytics-endpoint scans (the bigger lever)

### B4 (do FIRST — measurement) — cache hit/miss/eviction telemetry
`core/metrics.py` + the timing middleware already record per-path p95 (`main.py:389-396`).
Add per-cache hit/miss/eviction counters in `core/cache.py` so before/after is measured,
not assumed. Effort: ~0.5 day. Risk: none.

### B1 (HIGH) — split the cache by key space
In `core/cache.py`, add two dedicated caches beside the shared one:
- per-NPI cache (`@cached_npi_query`, ~1024 entries, 6–8h TTL) → used by `network/{npi}`,
  `temporal/providers/{npi}`, `diagnoses/{npi}`.
- per-code cache (~1024 entries) → `billing-codes/*`.

The 256-slot general cache then only holds the low-cardinality global aggregates it was
sized for. Expected: repeat provider/code lookups go from ~10% → 60–80% hit rate; aggregates
stop being evicted. Additive and behavior-preserving. Effort: ~1 day. Risk: low.

### B2 (HIGH — biggest end-to-end win) — precompute zero-parameter global aggregates
The whole-dataset aggregates that take no user parameters — `temporal/system-patterns`,
`billing-codes/top-codes`, `billing-codes/diagnosis-flags` — are identical for everyone and
change only when the Parquet or the scan changes. Compute them at **scan completion** and
persist to a `precomputed_analyses.json`, reusing the existing prescan-cache lifecycle in
`core/store.py` (write-to-disk → GCS sync → invalidate only when the dataset *filename*
changes, `store.py:59-67`). Serve from memory/disk in <50ms; **no more 503/504 on Cloud Run.**
The one thing to get right is invalidation — hook into `set_prescanned`/`append_prescanned`
plus the existing filename policy. Effort: ~1–2 days. Risk: low–medium (invalidation).

### B3 (MEDIUM) — make TTL match data volatility
The Parquet is static between redeploys/rescans, so 1h TTL is needlessly short for anything
that survives B1/B2. Key residual dynamic queries by dataset version and lengthen TTL.
Largely redundant once B1+B2 land. Effort: ~0.5 day.

---

## Suggested sequence & expected impact

| Order | Change | Lever | Effort | Impact |
|---|---|---|---|---|
| 1 | B4 telemetry (baseline) | cache | ~0.5d | measurement only |
| 2 | B2 precompute globals | cache | ~1–2d | kills 20–40s scans; no more 503s |
| 3 | B1 split NPI/code caches | cache | ~1d | detail-page panels warm to <100ms |
| 4 | A1 related.py 3→1 CTE | batch | ~0.5d | ~3× faster Related panel |
| 5 | A2 list-fallback batching | batch | ~1d | local/self-host only (prod guarded) |

B2 + B1 + A1 first is what makes the **provider-detail page feel instant end-to-end** — its
core already loads from the prescan cache; these warm/eliminate the four slow sub-panels.

## Verification (no 2.7GB Parquet needed)
The correctness-critical logic is verifiable against a **small synthetic DuckDB Parquet**
with the same schema — no real data or GCS required:
- B1/B4: unit-test the cache decorators/counters directly (pure `cachetools`).
- A1: build a tiny synthetic parquet, run the OLD 3 queries and the NEW single-CTE query,
  assert identical result sets (including the BENE_ID-absent case).
- B2: verify the precomputed aggregate matches the live query on the synthetic fixture, and
  that changing the dataset filename invalidates it.
Then run the existing suite: `backend/tests/` (`pytest`). End-to-end (route → app → GCS)
still needs a real deploy, but the logic above is fully testable in isolation.

## Do-not-touch (already optimal)
Scan batch pipeline · rescore MUP preload · timelines-batch endpoint · network ego-graph ·
NPPES/license enrichment · geography/states/specialty/anomalies/demographics (prescan-served).
