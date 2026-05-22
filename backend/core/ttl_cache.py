"""
Tiny TTL cache decorator for expensive read-only service functions.

The Analytics endpoints (claim-patterns/summary, billing-codes/top-codes,
beneficiary-fraud/summary, etc.) scan the parquet via DuckDB and take
1-18s per call. Their underlying data only changes when the parquet
itself changes, so caching for an hour is safe and turns repeat page
loads into instant responses.

Usage:
    @ttl_cached(seconds=3600)
    async def get_summary():
        ...
"""
import asyncio
import functools
import threading
import time
from typing import Any, Callable


def ttl_cached(seconds: int = 3600):
    """Decorator that memoizes an async OR sync function for `seconds` seconds.

    Cache key is the positional + keyword args. Cache lives for the lifetime
    of the process; restart uvicorn to clear it.

    NOTE: only safe for read-only functions whose output depends only on
    their arguments and the underlying parquet (which changes rarely).
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        cache: dict[tuple, tuple[float, Any]] = {}

        if asyncio.iscoroutinefunction(fn):
            async_lock = asyncio.Lock()

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                key = (args, tuple(sorted(kwargs.items())))
                now = time.time()
                hit = cache.get(key)
                if hit is not None and (now - hit[0]) < seconds:
                    return hit[1]
                async with async_lock:
                    hit = cache.get(key)
                    if hit is not None and (now - hit[0]) < seconds:
                        return hit[1]
                    result = await fn(*args, **kwargs)
                    cache[key] = (time.time(), result)
                    return result

            def clear() -> None:
                cache.clear()
            async_wrapper.cache_clear = clear  # type: ignore[attr-defined]
            return async_wrapper

        # Sync path
        sync_lock = threading.Lock()

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            hit = cache.get(key)
            if hit is not None and (now - hit[0]) < seconds:
                return hit[1]
            with sync_lock:
                hit = cache.get(key)
                if hit is not None and (now - hit[0]) < seconds:
                    return hit[1]
                result = fn(*args, **kwargs)
                cache[key] = (time.time(), result)
                return result

        def clear_sync() -> None:
            cache.clear()
        sync_wrapper.cache_clear = clear_sync  # type: ignore[attr-defined]
        return sync_wrapper

    return decorator
