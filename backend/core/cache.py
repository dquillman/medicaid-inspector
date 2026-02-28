import functools
import hashlib
import json
from cachetools import TTLCache
from core.config import settings

# Separate caches for different TTLs
_query_cache: TTLCache = TTLCache(maxsize=256, ttl=settings.CACHE_TTL)
_nppes_cache: TTLCache = TTLCache(maxsize=4096, ttl=settings.NPPES_CACHE_TTL)


def _make_key(*args, **kwargs) -> str:
    raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def cached_query(func):
    """Decorator: cache return value in _query_cache keyed by all arguments."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = _make_key(func.__name__, *args, **kwargs)
        if key in _query_cache:
            return _query_cache[key]
        result = func(*args, **kwargs)
        _query_cache[key] = result
        return result
    return wrapper


def cached_nppes(func):
    """Decorator: cache NPPES results for 24 hours."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        key = _make_key(func.__name__, *args, **kwargs)
        if key in _nppes_cache:
            return _nppes_cache[key]
        result = await func(*args, **kwargs)
        _nppes_cache[key] = result
        return result
    return wrapper


def invalidate_query_cache():
    _query_cache.clear()
