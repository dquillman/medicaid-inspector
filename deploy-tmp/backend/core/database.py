"""
SQLite database for critical app state.

Provides a migration path from JSON files to SQLite for write-heavy stores.
Currently migrates: users, sessions.
Future: audit_log, review_queue.

Uses sync sqlite3 with asyncio.to_thread for async compatibility.
"""
import asyncio
import json
import logging
import pathlib
import sqlite3
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

_DB_PATH = pathlib.Path(__file__).parent.parent / "app.db"
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    """Return (or create) the singleton SQLite connection."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
    return _conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username    TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            salt        TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'viewer',
            display_name TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            username    TEXT NOT NULL,
            created_at  REAL NOT NULL,
            FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL NOT NULL,
            action_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id   TEXT NOT NULL,
            user        TEXT NOT NULL DEFAULT 'system',
            details     TEXT,
            ip_address  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);

        CREATE TABLE IF NOT EXISTS review_queue (
            npi         TEXT PRIMARY KEY,
            risk_score  REAL NOT NULL DEFAULT 0.0,
            flags       TEXT NOT NULL DEFAULT '[]',
            signal_results TEXT NOT NULL DEFAULT '[]',
            total_paid  REAL NOT NULL DEFAULT 0,
            total_claims INTEGER NOT NULL DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'pending',
            notes       TEXT NOT NULL DEFAULT '',
            assigned_to TEXT,
            priority    TEXT NOT NULL DEFAULT 'medium',
            due_date    TEXT,
            documents   TEXT NOT NULL DEFAULT '[]',
            hours_logged TEXT NOT NULL DEFAULT '[]',
            total_hours REAL NOT NULL DEFAULT 0.0,
            audit_trail TEXT NOT NULL DEFAULT '[]',
            added_at    REAL NOT NULL,
            updated_at  REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status);
        CREATE INDEX IF NOT EXISTS idx_review_risk ON review_queue(risk_score DESC);
    """)
    conn.commit()
    log.info("[database] SQLite tables initialized at %s", _DB_PATH)


def migrate_users_from_json(users_json_path: pathlib.Path) -> int:
    """
    Import users from the JSON file into SQLite (one-time migration).
    Skips users that already exist in SQLite.
    Returns count of migrated users.
    """
    if not users_json_path.exists():
        return 0

    try:
        raw = json.loads(users_json_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[database] Could not read users JSON for migration: %s", e)
        return 0

    # Parse various JSON formats
    users_list = []
    if isinstance(raw, dict):
        if "users" in raw and isinstance(raw["users"], list):
            users_list = raw["users"]
        else:
            # Old email-keyed format
            for email, data in raw.items():
                users_list.append({
                    "username": email,
                    "password_hash": data.get("password_hash", ""),
                    "salt": data.get("salt", ""),
                    "role": data.get("role", "viewer"),
                    "display_name": data.get("display_name", email),
                    "created_at": data.get("created_at", time.time()),
                })
    elif isinstance(raw, list):
        users_list = raw

    conn = _get_conn()
    migrated = 0
    for u in users_list:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO users
                   (username, password_hash, salt, role, display_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    u["username"],
                    u.get("password_hash", ""),
                    u.get("salt", ""),
                    u.get("role", "viewer"),
                    u.get("display_name", u["username"]),
                    u.get("created_at", time.time()),
                ),
            )
            migrated += 1
        except Exception as e:
            log.warning("[database] Skipping user %s: %s", u.get("username"), e)

    conn.commit()
    if migrated:
        log.info("[database] Migrated %d users from JSON to SQLite", migrated)
    return migrated


# ── Generic query helpers ────────────────────────────────────────────────────

def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Execute a SQL statement and return the cursor."""
    conn = _get_conn()
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT and return list of dicts."""
    conn = _get_conn()
    cursor = conn.execute(sql, params)
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


async def execute_async(sql: str, params: tuple = ()) -> None:
    """Async wrapper around execute."""
    await asyncio.to_thread(execute, sql, params)


async def query_async(sql: str, params: tuple = ()) -> list[dict]:
    """Async wrapper around query."""
    return await asyncio.to_thread(query, sql, params)


def close() -> None:
    """Close the database connection."""
    global _conn
    if _conn:
        _conn.close()
        _conn = None
