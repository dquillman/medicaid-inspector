"""
Parallel range downloader for the Medicaid provider-spending parquet.

GCS supports HTTP range requests natively, so an 8-way concurrent fetch
saturates the pipe faster than the in-app single-stream downloader.
Atomic .tmp → rename means the live file stays intact until the new one
finishes — uvicorn keeps serving the old data during the download.

Usage:
    python backend/scripts/download_medicaid_parquet.py [--workers 8]
"""
import argparse
import asyncio
import functools
import logging
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

import httpx

_BACKEND = pathlib.Path(__file__).parent.parent
_TARGET = _BACKEND / "data" / "medicaid-provider-spending.parquet"
_TMP = _BACKEND / "data" / "medicaid-provider-spending.parquet.tmp"
_URL = "https://storage.googleapis.com/medicaid-inspector-data/medicaid-provider-spending.parquet"

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")


# Shared progress state across all workers
_state = {"bytes_done": 0, "bytes_total": 0, "started": 0.0}


async def fetch_range(client: httpx.AsyncClient, url: str, dest: pathlib.Path,
                      start: int, end: int, worker_id: int) -> None:
    """Pull one byte range and write it at its offset. Independent file
    handles per worker — concurrent writes at non-overlapping offsets are
    safe on Windows + Linux + macOS."""
    headers = {"Range": f"bytes={start}-{end}"}
    async with client.stream("GET", url, headers=headers, timeout=None) as resp:
        resp.raise_for_status()
        with open(dest, "r+b") as fh:
            fh.seek(start)
            async for chunk in resp.aiter_bytes(chunk_size=1_048_576):
                fh.write(chunk)
                _state["bytes_done"] += len(chunk)


async def reporter():
    """Background progress reporter — prints every 5 seconds."""
    while True:
        await asyncio.sleep(5)
        done = _state["bytes_done"]
        total = _state["bytes_total"]
        elapsed = time.time() - _state["started"]
        rate = done / elapsed if elapsed > 0 else 0
        pct = (done / total * 100) if total else 0
        eta = ((total - done) / rate) if rate > 0 else 0
        print(f"  {done/1e9:.2f} / {total/1e9:.2f} GB  ({pct:.1f}%)  "
              f"rate={rate/1e6:.1f} MB/s  ETA={eta:.0f}s")


async def run(workers: int, url: str) -> None:
    print(f"Probing {url} …")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        head = await client.head(url)
        head.raise_for_status()
        total = int(head.headers.get("content-length", 0))
        last_modified = head.headers.get("last-modified", "?")

    if total < 1_000_000:
        print(f"ERROR: HEAD returned tiny size ({total}) — refusing to download")
        sys.exit(1)

    print(f"  size: {total/1e9:.2f} GB  last-modified: {last_modified}")
    print(f"  destination: {_TARGET}")
    print(f"  workers: {workers}")
    print()

    # Pre-allocate the tmp file so seek+write at offsets works
    _TMP.parent.mkdir(parents=True, exist_ok=True)
    with open(_TMP, "wb") as f:
        f.truncate(total)

    chunk_size = (total + workers - 1) // workers
    ranges = [(i * chunk_size, min((i + 1) * chunk_size - 1, total - 1))
              for i in range(workers)]

    _state["bytes_total"] = total
    _state["started"] = time.time()

    reporter_task = asyncio.create_task(reporter())
    limits = httpx.Limits(max_connections=workers * 2, max_keepalive_connections=workers * 2)
    async with httpx.AsyncClient(http2=False, limits=limits) as client:
        tasks = [
            fetch_range(client, url, _TMP, start, end, i)
            for i, (start, end) in enumerate(ranges)
        ]
        await asyncio.gather(*tasks)
    reporter_task.cancel()

    elapsed = time.time() - _state["started"]
    print()
    print(f"Download complete: {total/1e9:.2f} GB in {elapsed:.1f}s "
          f"({total/elapsed/1e6:.1f} MB/s average)")

    # Atomic swap. On Windows, rename across existing file requires
    # the target not to be open; the in-app downloader can handle this
    # because uvicorn keeps the parquet read-only for DuckDB queries.
    print(f"Renaming {_TMP.name} → {_TARGET.name} …")
    if _TARGET.exists():
        _TARGET.unlink()
    _TMP.rename(_TARGET)
    size_gb = _TARGET.stat().st_size / 1e9
    print(f"DONE — {_TARGET} ({size_gb:.2f} GB)")
    print()
    print("Next steps:")
    print("  1. Backend cache must be invalidated. Either restart uvicorn or")
    print("     POST /api/admin/dataset-refresh.")
    print("  2. Re-run the rescore so signals reflect the new dataset.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--url", default=_URL)
    args = ap.parse_args()
    asyncio.run(run(args.workers, args.url))
