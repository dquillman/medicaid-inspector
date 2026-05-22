"""
Bulk local cache of the CMS MUP-by-Provider dataset, stored as Parquet and
queried via DuckDB so the diagnosis_procedure_mismatch signal can run during
batch scans without per-NPI API calls.

Workflow:
    1. download_and_convert() — paginates the CMS JSON API in parallel,
       writes JSONL to disk, then DuckDB COPY converts to parquet
    2. lookup(npi)            — point query against the parquet (in-process)

The CMS CSV CDN throttles per-connection so aggressively that a single-stream
download takes hours. The JSON data API is unthrottled and returns ~25 MB/s
with 8 parallel workers — full dataset (~1.26M rows, ~3 GB JSON) lands in
2-3 minutes and converts to a ~200 MB parquet.
"""
import json
import logging
import pathlib
import threading
import time
from typing import Optional

import httpx
import duckdb

log = logging.getLogger(__name__)

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
_MUP_PARQUET = _DATA_DIR / "mup-by-provider.parquet"
_MUP_PARQUET_TMP = _DATA_DIR / "mup-by-provider.parquet.building"
_MUP_JSONL_TMP = _DATA_DIR / "mup-by-provider.jsonl.tmp"

# CMS data API for MUP-by-Provider (annual release; same ID across years).
_DATASET_ID = "8889d81e-2ee7-448f-8713-f071038289b5"
_API_URL = f"https://data.cms.gov/data-api/v1/dataset/{_DATASET_ID}/data"
_TOTAL_ROWS_UPPER = 1_260_000  # empirical upper bound; empty pages stop early
_DEFAULT_WORKERS = 8
_DEFAULT_PAGE_SIZE = 5000

# In-process download progress (one downloader at a time)
_download_state: dict = {
    "active": False,
    "bytes_done": 0,        # cumulative response bytes — drives the UI progress bar
    "bytes_total": 0,       # estimated final byte count (set after first page)
    "rows_done": 0,
    "rows_total": _TOTAL_ROWS_UPPER,
    "done": False,
    "error": None,
    "phase": "idle",        # idle | downloading | converting | done
}
_download_lock = threading.Lock()

# Per-thread DuckDB connection for point lookups
_thread_local = threading.local()


def is_local() -> bool:
    return _MUP_PARQUET.exists() and _MUP_PARQUET.stat().st_size > 1_000_000


def get_local_path() -> pathlib.Path:
    return _MUP_PARQUET


def status() -> dict:
    info: dict = {
        "is_local":      is_local(),
        "local_path":    str(_MUP_PARQUET) if is_local() else None,
        "file_size_mb":  None,
        "row_count":     None,
        "download":      dict(_download_state),
    }
    if is_local():
        try:
            info["file_size_mb"] = round(_MUP_PARQUET.stat().st_size / 1_048_576, 1)
        except OSError:
            pass
    # row_count populated lazily via /admin/mup-status endpoint to avoid blocking
    return info


def _connection() -> duckdb.DuckDBPyConnection:
    if not hasattr(_thread_local, "con") or _thread_local.con is None:
        _thread_local.con = duckdb.connect(database=":memory:")
    return _thread_local.con


def lookup(npi: str) -> Optional[dict]:
    """Point-query the local MUP parquet for one NPI. Returns None on miss."""
    if not is_local():
        return None
    if not npi.isdigit() or len(npi) != 10:
        return None
    try:
        con = _connection()
        path = str(_MUP_PARQUET).replace("\\", "/")
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}') WHERE Rndrng_NPI = ? LIMIT 1",
            [npi],
        ).fetchall()
        if not rows:
            return None
        cols = [d[0] for d in con.description]
        return dict(zip(cols, rows[0]))
    except Exception as e:
        log.warning("[mup_cache] lookup failed for NPI=%s: %s", npi, e)
        return None


def row_count() -> Optional[int]:
    if not is_local():
        return None
    try:
        con = _connection()
        path = str(_MUP_PARQUET).replace("\\", "/")
        row = con.execute(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()
        return int(row[0]) if row else None
    except Exception as e:
        log.warning("[mup_cache] row_count failed: %s", e)
        return None


async def _fetch_page(client: "httpx.AsyncClient", offset: int, size: int) -> list[dict]:
    """Fetch one paginated page of MUP rows. 3 retries on transient errors."""
    for attempt in range(3):
        try:
            resp = await client.get(_API_URL, params={"size": size, "offset": offset}, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                _download_state["bytes_done"] += len(resp.content)
                return data
            return []
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.warning("[mup_cache] page offset=%d attempt=%d failed: %s",
                        offset, attempt + 1, e)
            import asyncio
            await asyncio.sleep(1 + attempt * 2)
    log.error("[mup_cache] giving up on offset=%d after 3 attempts", offset)
    return []


async def _page_worker(client: "httpx.AsyncClient", queue, fh, fh_lock,
                       page_size: int) -> None:
    import asyncio
    while True:
        offset = await queue.get()
        try:
            if offset is None:
                return
            rows = await _fetch_page(client, offset, page_size)
            if not rows:
                continue
            async with fh_lock:
                for row in rows:
                    fh.write(json.dumps(row, separators=(",", ":")))
                    fh.write("\n")
                _download_state["rows_done"] += len(rows)
        finally:
            queue.task_done()


async def download_and_convert(
    workers: int = _DEFAULT_WORKERS,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> None:
    """Build the local MUP parquet by paginating the CMS JSON API in parallel.

    Bypasses the CDN's per-connection throttle on the CSV distribution
    (single-stream takes hours; this approach lands in ~2-3 min at ~25 MB/s).
    """
    import asyncio
    global _download_state
    with _download_lock:
        if _download_state["active"]:
            log.info("[mup_cache] download already active — skipping")
            return
        _download_state = {
            "active": True,
            "bytes_done": 0,
            "bytes_total": 3_000_000_000,  # ~3 GB JSON estimate for the progress bar
            "rows_done": 0,
            "rows_total": _TOTAL_ROWS_UPPER,
            "done": False,
            "error": None,
            "phase": "downloading",
        }

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _MUP_JSONL_TMP.exists():
        _MUP_JSONL_TMP.unlink()

    try:
        queue: asyncio.Queue = asyncio.Queue()
        n_pages = (_TOTAL_ROWS_UPPER + page_size - 1) // page_size
        for i in range(n_pages):
            queue.put_nowait(i * page_size)
        for _ in range(workers):
            queue.put_nowait(None)

        log.info("[mup_cache] fetching ~%d rows across %d pages with %d workers",
                 _TOTAL_ROWS_UPPER, n_pages, workers)

        with open(_MUP_JSONL_TMP, "w", encoding="utf-8") as fh:
            fh_lock = asyncio.Lock()
            limits = httpx.Limits(
                max_connections=workers * 2,
                max_keepalive_connections=workers * 2,
            )
            async with httpx.AsyncClient(http2=False, limits=limits) as client:
                tasks = [
                    asyncio.create_task(_page_worker(client, queue, fh, fh_lock, page_size))
                    for _ in range(workers)
                ]
                await asyncio.gather(*tasks)

        # Update bytes_total to the actual JSON size so progress reads 100% on done.
        _download_state["bytes_total"] = _download_state["bytes_done"]
        _download_state["phase"] = "converting"
        log.info("[mup_cache] %d rows fetched (%.1f MB) — converting to parquet",
                 _download_state["rows_done"],
                 _download_state["bytes_done"] / 1_048_576)

        def _convert():
            con = duckdb.connect(database=":memory:")
            jsonl_path = str(_MUP_JSONL_TMP).replace("\\", "/")
            parquet_tmp_path = str(_MUP_PARQUET_TMP).replace("\\", "/")
            # NOTE: do NOT pass format='newline_delimited' — that triggers the
            # MAP(VARCHAR, VARCHAR) shape. read_json_auto() infers ND-JSON from
            # the .jsonl extension and produces flat columns.
            con.execute(f"""
                COPY (
                    SELECT * FROM read_json_auto('{jsonl_path}')
                ) TO '{parquet_tmp_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
            if _MUP_PARQUET.exists():
                _MUP_PARQUET.unlink()
            _MUP_PARQUET_TMP.rename(_MUP_PARQUET)
            try:
                _MUP_JSONL_TMP.unlink()
            except OSError:
                pass

        await asyncio.to_thread(_convert)

        _download_state["phase"] = "done"
        _download_state["done"] = True
        _download_state["active"] = False
        log.info("[mup_cache] parquet built at %s (%.1f MB)",
                 _MUP_PARQUET, _MUP_PARQUET.stat().st_size / 1_048_576)
    except Exception as e:
        log.error("[mup_cache] download/convert failed: %s", e)
        _download_state["error"] = str(e)
        _download_state["active"] = False
        _download_state["phase"] = "idle"
        for p in (_MUP_JSONL_TMP, _MUP_PARQUET_TMP):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
