"""
Metrics & observability — in-memory counters for request timing, scan stats, cache hits.
"""
import time
import threading
from collections import defaultdict
from typing import Optional


_lock = threading.Lock()

# ── Request metrics ──────────────────────────────────────────────────────────
_request_counts: dict[str, int] = defaultdict(int)          # path → count
_request_times: dict[str, list[float]] = defaultdict(list)  # path → [durations]
_error_counts: dict[str, int] = defaultdict(int)            # path → error count
_status_counts: dict[int, int] = defaultdict(int)           # status_code → count

# ── Scan metrics ─────────────────────────────────────────────────────────────
_scan_metrics: dict = {
    "total_scans": 0,
    "total_providers_scanned": 0,
    "total_scan_errors": 0,
    "last_scan_duration_s": None,
    "last_scan_at": None,
}

# ── Cache metrics ────────────────────────────────────────────────────────────
_cache_hits: int = 0
_cache_misses: int = 0

# ── System start time ────────────────────────────────────────────────────────
_start_time: float = time.time()


# ── Public API ───────────────────────────────────────────────────────────────

def record_request(path: str, method: str, status_code: int, duration: float):
    """Record a single request's metrics."""
    key = f"{method} {path}"
    with _lock:
        _request_counts[key] += 1
        _status_counts[status_code] += 1
        # Keep last 100 durations per endpoint to compute avg/p95
        times = _request_times[key]
        times.append(duration)
        if len(times) > 100:
            _request_times[key] = times[-100:]
        if status_code >= 400:
            _error_counts[key] += 1


def record_scan(providers_scanned: int, duration_s: float, error: bool = False):
    """Record scan batch completion."""
    with _lock:
        _scan_metrics["total_scans"] += 1
        _scan_metrics["total_providers_scanned"] += providers_scanned
        _scan_metrics["last_scan_duration_s"] = round(duration_s, 2)
        _scan_metrics["last_scan_at"] = time.time()
        if error:
            _scan_metrics["total_scan_errors"] += 1


def record_cache_hit():
    global _cache_hits
    with _lock:
        _cache_hits += 1


def record_cache_miss():
    global _cache_misses
    with _lock:
        _cache_misses += 1


def get_metrics() -> dict:
    """Return all metrics as a JSON-serializable dict."""
    with _lock:
        # Top endpoints by request count
        top_endpoints = sorted(_request_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        endpoint_stats = []
        for key, count in top_endpoints:
            times = _request_times.get(key, [])
            avg_ms = round(sum(times) / len(times) * 1000, 1) if times else 0
            sorted_times = sorted(times)
            p95_ms = round(sorted_times[int(len(sorted_times) * 0.95)] * 1000, 1) if len(sorted_times) >= 2 else avg_ms
            errors = _error_counts.get(key, 0)
            endpoint_stats.append({
                "endpoint": key,
                "count": count,
                "avg_ms": avg_ms,
                "p95_ms": p95_ms,
                "errors": errors,
            })

        total_requests = sum(_request_counts.values())
        total_errors = sum(_error_counts.values())

        cache_total = _cache_hits + _cache_misses
        cache_hit_rate = round(_cache_hits / cache_total * 100, 1) if cache_total > 0 else 0.0

        uptime_s = round(time.time() - _start_time, 1)

        return {
            "uptime_seconds": uptime_s,
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_pct": round(total_errors / total_requests * 100, 2) if total_requests > 0 else 0,
            "status_codes": dict(_status_counts),
            "endpoints": endpoint_stats,
            "scan": dict(_scan_metrics),
            "cache": {
                "hits": _cache_hits,
                "misses": _cache_misses,
                "hit_rate_pct": cache_hit_rate,
            },
        }


def get_prometheus_text() -> str:
    """Return metrics in Prometheus text exposition format."""
    lines = []
    uptime = time.time() - _start_time

    lines.append("# HELP mfi_uptime_seconds Time since server start")
    lines.append("# TYPE mfi_uptime_seconds gauge")
    lines.append(f"mfi_uptime_seconds {uptime:.1f}")

    with _lock:
        total_requests = sum(_request_counts.values())
        total_errors = sum(_error_counts.values())

        lines.append("# HELP mfi_requests_total Total HTTP requests")
        lines.append("# TYPE mfi_requests_total counter")
        lines.append(f"mfi_requests_total {total_requests}")

        lines.append("# HELP mfi_errors_total Total HTTP errors (4xx/5xx)")
        lines.append("# TYPE mfi_errors_total counter")
        lines.append(f"mfi_errors_total {total_errors}")

        lines.append("# HELP mfi_http_requests_by_status HTTP requests by status code")
        lines.append("# TYPE mfi_http_requests_by_status counter")
        for code, count in sorted(_status_counts.items()):
            lines.append(f'mfi_http_requests_by_status{{code="{code}"}} {count}')

        lines.append("# HELP mfi_scans_total Total scan batches completed")
        lines.append("# TYPE mfi_scans_total counter")
        lines.append(f"mfi_scans_total {_scan_metrics['total_scans']}")

        lines.append("# HELP mfi_providers_scanned_total Total providers scanned across all batches")
        lines.append("# TYPE mfi_providers_scanned_total counter")
        lines.append(f"mfi_providers_scanned_total {_scan_metrics['total_providers_scanned']}")

        lines.append("# HELP mfi_cache_hits_total Cache hits")
        lines.append("# TYPE mfi_cache_hits_total counter")
        lines.append(f"mfi_cache_hits_total {_cache_hits}")

        lines.append("# HELP mfi_cache_misses_total Cache misses")
        lines.append("# TYPE mfi_cache_misses_total counter")
        lines.append(f"mfi_cache_misses_total {_cache_misses}")

    lines.append("")
    return "\n".join(lines)
