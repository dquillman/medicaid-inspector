"""
DuckDB in-process client.
Uses thread-local connections so each asyncio.to_thread worker gets its own
DuckDB connection — avoiding the "shared connection is not thread-safe" bug.
"""
import asyncio
import logging
import pathlib
import threading
import duckdb
from core.config import settings
from core.cache import cached_query

log = logging.getLogger(__name__)

_thread_local = threading.local()

# Default location for the locally-downloaded Parquet file.
# Can be overridden by setting LOCAL_PARQUET_PATH in .env
_DEFAULT_LOCAL_PARQUET = pathlib.Path(__file__).parent / "medicaid-provider-spending.parquet"


def _resolve_local_path() -> pathlib.Path:
    """Return the configured local path if set, otherwise the default location."""
    if settings.LOCAL_PARQUET_PATH:
        return pathlib.Path(settings.LOCAL_PARQUET_PATH)
    return _DEFAULT_LOCAL_PARQUET


# _LOCAL_PARQUET always points to where the in-app download saves the file
_LOCAL_PARQUET = _DEFAULT_LOCAL_PARQUET


# Characters that could break out of a single-quoted SQL string literal
# (e.g., read_parquet('...')). These must never appear in a parquet path
# because paths are interpolated into SQL as f-strings in many call sites.
_SQL_UNSAFE_CHARS = ("'", '"', ";", "\n", "\r", "\x00", "--", "/*", "*/")


def _assert_sql_safe_path(path: str) -> str:
    """
    Defense-in-depth: reject parquet paths that contain SQL metacharacters.
    The parquet path comes from config/env, but this guards against misconfig
    or any future user-influenced input that reaches the dataset URL.
    Raises ValueError on anything suspicious.
    """
    if not path:
        raise ValueError("Parquet path is empty")
    for bad in _SQL_UNSAFE_CHARS:
        if bad in path:
            raise ValueError(
                f"Parquet path contains unsafe character sequence {bad!r}"
            )
    return path


def get_parquet_path() -> str:
    """Return local path if a valid file exists there, otherwise the remote URL.

    The returned string is guaranteed to contain no SQL metacharacters, so it
    is safe to interpolate into `read_parquet('...')`.
    """
    p = _resolve_local_path()
    if p.exists() and p.stat().st_size > 1_000_000:
        # Validate the Parquet file has proper magic bytes (PAR1 header)
        try:
            with open(p, "rb") as f:
                header = f.read(4)
            if header == b"PAR1":
                return _assert_sql_safe_path(str(p).replace("\\", "/"))
            else:
                log.warning("Local Parquet file has invalid header — using remote URL")
        except Exception:
            pass
    return _assert_sql_safe_path(settings.PARQUET_URL)


def is_local() -> bool:
    p = _resolve_local_path()
    return p.exists() and p.stat().st_size > 1_000_000


def get_local_path() -> pathlib.Path:
    """The resolved local path (may or may not exist yet)."""
    return _resolve_local_path()


# Module-level aliases (used by SQL helpers — regenerated on each call via get_parquet_path)
PARQUET = settings.PARQUET_URL  # kept for backwards compat; prefer get_parquet_path()
PARQUET_SRC = f"read_parquet('{PARQUET}')"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a per-thread DuckDB connection, creating it on first use."""
    if not hasattr(_thread_local, "con") or _thread_local.con is None:
        con = duckdb.connect(database=":memory:")
        con.execute("INSTALL httpfs;")
        con.execute("LOAD httpfs;")
        con.execute("SET http_keep_alive=true;")
        con.execute("SET http_retries=3;")
        con.execute("SET threads=2;")
        _thread_local.con = con
    return _thread_local.con


def _run_query_uncached(sql: str, params: tuple = ()) -> list[dict]:
    con = get_connection()
    rel = con.execute(sql, params) if params else con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


@cached_query
def run_query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute SQL and return rows as list of dicts. Results are cached per SQL string + params."""
    return _run_query_uncached(sql, params)


async def query_async(sql: str, params: tuple = ()) -> list[dict]:
    """Non-blocking wrapper — runs run_query in a thread pool."""
    return await asyncio.to_thread(run_query, sql, params)


# ------------------------------------------------------------------
# Pre-built SQL fragments
# ------------------------------------------------------------------
_state_col_checked = False
_state_col: str | None = None


def detect_state_column() -> str | None:
    """Check the Parquet schema once for a billing provider state column. Cached after first call."""
    global _state_col_checked, _state_col
    if _state_col_checked:
        return _state_col
    src = f"read_parquet('{get_parquet_path()}')"
    try:
        rows = _run_query_uncached(f"""
            SELECT column_name
            FROM (DESCRIBE SELECT * FROM {src} LIMIT 0)
            WHERE lower(column_name) LIKE '%state%'
            LIMIT 1
        """)
        _state_col = rows[0]["column_name"] if rows else None
        _state_col_checked = True
        print(f"[duckdb] State column: {_state_col!r}")
    except Exception as e:
        print(f"[duckdb] Could not detect state column: {e}")
        _state_col_checked = True
        _state_col = None
    return _state_col


def count_providers_sql(where: str = "") -> str:
    """Total distinct provider count, optionally filtered by a WHERE clause."""
    src = f"read_parquet('{get_parquet_path()}')"
    where_clause = f"WHERE {where}" if where else ""
    return f"""
    SELECT COUNT(DISTINCT BILLING_PROVIDER_NPI_NUM) AS total
    FROM {src}
    {where_clause}
    """


def provider_aggregate_sql(
    where: str = "",
    order: str = "total_paid DESC",
    limit: int | None = 100,
    offset: int = 0,
) -> str:
    src = f"read_parquet('{get_parquet_path()}')"
    where_clause = f"WHERE {where}" if where else ""
    limit_clause = f"LIMIT {limit} OFFSET {offset}" if limit is not None else ""
    return f"""
    SELECT
        BILLING_PROVIDER_NPI_NUM                            AS npi,
        SUM(TOTAL_PAID)                                     AS total_paid,
        SUM(TOTAL_CLAIMS)                                   AS total_claims,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)                     AS total_beneficiaries,
        COUNT(DISTINCT HCPCS_CODE)                          AS distinct_hcpcs,
        COUNT(DISTINCT CLAIM_FROM_MONTH)                    AS active_months,
        MIN(CLAIM_FROM_MONTH)                               AS first_month,
        MAX(CLAIM_FROM_MONTH)                               AS last_month,
        CAST(SUM(TOTAL_PAID) AS DOUBLE) /
            NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0)      AS revenue_per_beneficiary,
        CAST(SUM(TOTAL_CLAIMS) AS DOUBLE) /
            NULLIF(SUM(TOTAL_UNIQUE_BENEFICIARIES), 0)      AS claims_per_beneficiary
    FROM {src}
    {where_clause}
    GROUP BY BILLING_PROVIDER_NPI_NUM
    ORDER BY {order}
    {limit_clause}
    """
