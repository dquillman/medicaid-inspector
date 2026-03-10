"""
In-memory rate limiter for FastAPI.
Tracks request counts per IP per minute window.
"""
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class _RateBucket:
    """Sliding-window counter for a single IP."""
    __slots__ = ("counts",)

    def __init__(self):
        # minute_key -> count
        self.counts: dict[int, int] = {}

    def hit(self, limit: int) -> bool:
        """Record a hit. Returns True if under the limit, False if exceeded."""
        now = int(time.time())
        minute_key = now // 60
        # Prune old entries (keep only current minute)
        old_keys = [k for k in self.counts if k < minute_key]
        for k in old_keys:
            del self.counts[k]
        current = self.counts.get(minute_key, 0)
        if current >= limit:
            return False
        self.counts[minute_key] = current + 1
        return True


# Global buckets — keyed by IP address
_login_buckets: dict[str, _RateBucket] = defaultdict(_RateBucket)
_api_buckets: dict[str, _RateBucket] = defaultdict(_RateBucket)

# Limits
LOGIN_LIMIT_PER_MINUTE = 5
API_LIMIT_PER_MINUTE = 100


def check_login_rate(request: Request) -> None:
    """Call from login endpoint. Raises 429 if exceeded."""
    ip = request.client.host if request.client else "unknown"
    if not _login_buckets[ip].hit(LOGIN_LIMIT_PER_MINUTE):
        raise HTTPException(429, "Too many login attempts. Try again in a minute.")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """General API rate limiter — 100 requests/minute per IP."""

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        if not _api_buckets[ip].hit(API_LIMIT_PER_MINUTE):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a minute."},
            )
        return await call_next(request)
