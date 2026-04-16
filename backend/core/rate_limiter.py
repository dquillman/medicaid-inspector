"""
In-memory rate limiter for FastAPI.
Tracks request counts per IP per minute window.

IP resolution strategy:
- On Cloud Run / behind a trusted reverse proxy, the real client IP is in
  X-Forwarded-For.  Google's load balancer appends the real IP as the LAST
  entry of X-Forwarded-For (entries to the left can be spoofed by the client).
  We therefore take the LAST comma-separated value when the header is present.
- In local dev (no proxy), request.client.host is used directly.
- IMPORTANT: Never blindly trust the first X-Forwarded-For entry — it is
  trivially spoofable and would allow a single attacker to bypass rate limits
  by cycling fake IPs in that header.
"""
import os
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Set TRUSTED_PROXY=1 (or Cloud Run sets K_SERVICE) to enable X-Forwarded-For.
# When enabled we take the LAST entry (the one appended by our own load balancer).
_BEHIND_PROXY = bool(os.environ.get("TRUSTED_PROXY") or os.environ.get("K_SERVICE"))


def _get_client_ip(request: Request) -> str:
    """Resolve the real client IP safely.

    On Cloud Run the load balancer appends the real client IP as the rightmost
    value in X-Forwarded-For.  Taking the last entry is safe because only our
    own load balancer can add to the right side; the client controls only the
    leftmost values.
    """
    if _BEHIND_PROXY:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            # Take the last (rightmost) entry — set by the trusted LB, not the client
            last_ip = xff.split(",")[-1].strip()
            if last_ip:
                return last_ip
    return request.client.host if request.client else "unknown"


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
    """Call from login/register endpoints. Raises 429 if exceeded."""
    ip = _get_client_ip(request)
    if not _login_buckets[ip].hit(LOGIN_LIMIT_PER_MINUTE):
        raise HTTPException(429, "Too many login attempts. Try again in a minute.")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """General API rate limiter — 100 requests/minute per IP."""

    async def dispatch(self, request: Request, call_next):
        ip = _get_client_ip(request)
        if not _api_buckets[ip].hit(API_LIMIT_PER_MINUTE):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a minute."},
            )
        return await call_next(request)
