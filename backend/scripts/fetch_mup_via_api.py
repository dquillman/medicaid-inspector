"""
Build the local MUP-by-Provider parquet by paginating the CMS JSON API in
parallel. Bypasses the slow CSV CDN endpoint entirely.

Usage:
    python backend/scripts/fetch_mup_via_api.py [--workers 8] [--page-size 5000]

Output: backend/data/mup-by-provider.parquet
"""
import argparse
import asyncio
import json
import logging
import pathlib
import sys
import time

import httpx
import duckdb

_DATASET_ID = "8889d81e-2ee7-448f-8713-f071038289b5"
_API_URL = f"https://data.cms.gov/data-api/v1/dataset/{_DATASET_ID}/data"
_TOTAL_ROWS_UPPER = 1_260_000  # empirically determined — empty pages stop early

_BACKEND = pathlib.Path(__file__).parent.parent
_DATA_DIR = _BACKEND / "data"
_JSONL_TMP = _DATA_DIR / "mup-by-provider.jsonl.tmp"
_PARQUET = _DATA_DIR / "mup-by-provider.parquet"
_PARQUET_TMP = _DATA_DIR / "mup-by-provider.parquet.building"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("mup-fetcher")


async def fetch_page(client: httpx.AsyncClient, offset: int, size: int,
                     state: dict) -> list[dict]:
    for attempt in range(3):
        try:
            resp = await client.get(_API_URL, params={"size": size, "offset": offset}, timeout=60.0)
            resp.raise_for_status()
            rows = resp.json()
            if isinstance(rows, list):
                state["bytes"] += len(resp.content)
                return rows
            return []
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.warning("offset=%d attempt=%d failed: %s", offset, attempt + 1, e)
            await asyncio.sleep(1 + attempt * 2)
    log.error("offset=%d giving up after 3 attempts", offset)
    return []


async def worker(name: str, queue: asyncio.Queue, fh, fh_lock, state: dict,
                 page_size: int, client: httpx.AsyncClient) -> None:
    while True:
        offset = await queue.get()
        if offset is None:
            queue.task_done()
            return
        rows = await fetch_page(client, offset, page_size, state)
        if not rows:
            state["empty_pages"] += 1
            queue.task_done()
            continue
        # Write to JSONL under the lock — same file handle across workers
        async with fh_lock:
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":")))
                fh.write("\n")
            state["rows"] += len(rows)
        queue.task_done()


async def run(workers: int, page_size: int) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _JSONL_TMP.exists():
        _JSONL_TMP.unlink()

    state = {"rows": 0, "bytes": 0, "empty_pages": 0, "started": time.time()}
    queue: asyncio.Queue = asyncio.Queue()
    n_pages = (_TOTAL_ROWS_UPPER + page_size - 1) // page_size
    for i in range(n_pages):
        queue.put_nowait(i * page_size)

    # Reporter task
    async def report():
        while True:
            await asyncio.sleep(5)
            elapsed = time.time() - state["started"]
            rate = state["bytes"] / elapsed if elapsed > 0 else 0
            log.info("rows=%d bytes=%.1fMB rate=%.1fMB/s queue=%d empty=%d",
                     state["rows"], state["bytes"] / 1_048_576, rate / 1_048_576,
                     queue.qsize(), state["empty_pages"])

    reporter = asyncio.create_task(report())
    with open(_JSONL_TMP, "w", encoding="utf-8") as fh:
        fh_lock = asyncio.Lock()
        async with httpx.AsyncClient(
            http2=False,
            limits=httpx.Limits(max_connections=workers * 2, max_keepalive_connections=workers * 2),
        ) as client:
            ws = [
                asyncio.create_task(worker(f"w{i}", queue, fh, fh_lock, state, page_size, client))
                for i in range(workers)
            ]
            # Sentinels
            for _ in range(workers):
                queue.put_nowait(None)
            await asyncio.gather(*ws)
    reporter.cancel()

    elapsed = time.time() - state["started"]
    log.info("Fetch complete: %d rows in %.1fs (%.1fMB)",
             state["rows"], elapsed, state["bytes"] / 1_048_576)

    log.info("Converting JSONL → parquet via DuckDB…")
    con = duckdb.connect(database=":memory:")
    jsonl_path = str(_JSONL_TMP).replace("\\", "/")
    parquet_path = str(_PARQUET_TMP).replace("\\", "/")
    t0 = time.time()
    # Drop format='newline_delimited' — it makes DuckDB store rows as MAP.
    # Without it, ND-JSON is auto-detected from the extension and rows are flat.
    con.execute(f"""
        COPY (SELECT * FROM read_json_auto('{jsonl_path}'))
        TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    log.info("Parquet built in %.1fs — finalizing", time.time() - t0)

    if _PARQUET.exists():
        _PARQUET.unlink()
    _PARQUET_TMP.rename(_PARQUET)
    _JSONL_TMP.unlink()

    size_mb = _PARQUET.stat().st_size / 1_048_576
    log.info("DONE: %s — %.1f MB", _PARQUET, size_mb)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--page-size", type=int, default=5000)
    args = ap.parse_args()
    asyncio.run(run(args.workers, args.page_size))
