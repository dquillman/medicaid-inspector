"""
Role-Based Access Control (RBAC) store.
Manages users, roles, permissions, and session tokens.
Persists users to backend/users.json.
"""
import hashlib
import hmac
import json
import secrets
import time
import uuid
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

_USERS_FILE = pathlib.Path(__file__).parent.parent / "users.json"
_SESSIONS_FILE = pathlib.Path(__file__).parent.parent / "sessions.json"
_ADMIN_INIT_FLAG = pathlib.Path(__file__).parent.parent / ".admin_initialized"

# ── Roles & Permissions ──────────────────────────────────────────────────────

ROLES = {"admin", "investigator", "analyst", "viewer"}

# Actions mapped to each role (cumulative — higher roles include lower)
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {
        "read_providers",
        "read_reports",
        "read_review",
        "read_anomalies",
        "read_network",
        "read_summary",
    },
    "analyst": {
        # viewer permissions +
        "read_providers",
        "read_reports",
        "read_review",
        "read_anomalies",
        "read_network",
        "read_summary",
        # analyst-specific
        "run_scan",
        "run_smart_scan",
        "run_rescore",
        "generate_reports",
        "run_ml_training",
        "export_data",
    },
    "investigator": {
        # analyst permissions +
        "read_providers",
        "read_reports",
        "read_review",
        "read_anomalies",
        "read_network",
        "read_summary",
        "run_scan",
        "run_smart_scan",
        "run_rescore",
        "generate_reports",
        "run_ml_training",
        "export_data",
        # investigator-specific
        "modify_review",
        "assign_review",
        "add_notes",
        "log_hours",
        "bulk_update_review",
    },
    "admin": {
        # all permissions
        "read_providers",
        "read_reports",
        "read_review",
        "read_anomalies",
        "read_network",
        "read_summary",
        "run_scan",
        "run_smart_scan",
        "run_rescore",
        "generate_reports",
        "run_ml_training",
        "export_data",
        "modify_review",
        "assign_review",
        "add_notes",
        "log_hours",
        "bulk_update_review",
        # admin-specific
        "manage_users",
        "manage_alert_rules",
        "delete_data",
        "reset_scan",
    },
}

# ── In-memory session store ──────────────────────────────────────────────────

# token -> {username, created_at}
_sessions: dict[str, dict] = {}

# ── In-memory user cache ─────────────────────────────────────────────────────

_users: dict[str, dict] = {}


# ── Password hashing ─────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


# ── Disk persistence ─────────────────────────────────────────────────────────

def _load_users() -> dict[str, dict]:
    global _users
    try:
        if _USERS_FILE.exists():
            raw = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                # Could be old format (email -> {salt, password_hash, ...})
                # or new format {"users": [...]}
                if "users" in raw and isinstance(raw["users"], list):
                    _users = {u["username"]: u for u in raw["users"]}
                else:
                    # Old email-keyed format — migrate
                    _users = {}
                    for email, data in raw.items():
                        _users[email] = {
                            "username": email,
                            "password_hash": data.get("password_hash", ""),
                            "salt": data.get("salt", ""),
                            "role": data.get("role", "viewer"),
                            "display_name": data.get("display_name", email),
                            "created_at": data.get("created_at", time.time()),
                        }
            elif isinstance(raw, list):
                _users = {u["username"]: u for u in raw}
    except Exception as e:
        print(f"[auth_store] Could not load users: {e}")
    return _users


def _save_users() -> None:
    try:
        data = {"users": list(_users.values())}
        atomic_write_json(_USERS_FILE, data, indent=2)
        # Sync to GCS in background (non-blocking)
        try:
            from core.gcs_sync import upload_file
            upload_file("users.json")
        except Exception:
            pass
    except Exception as e:
        print(f"[auth_store] Could not save users: {e}")


def init_auth_store() -> None:
    """Load users and sessions from disk at startup. Create default admin if no users exist."""
    import os
    _load_users()
    load_sessions_from_disk()
    default_password = os.environ.get("ADMIN_PASSWORD")
    if not default_password:
        # No ADMIN_PASSWORD set — refuse to start with a known-weak default in
        # production. Generate a random password and print it once so the
        # operator can grab it from the Cloud Run logs on first deploy.
        import warnings
        default_password = secrets.token_urlsafe(16)
        warnings.warn(
            "[auth_store] ADMIN_PASSWORD env var is not set. "
            f"Generated one-time admin password: {default_password}  "
            "Set ADMIN_PASSWORD in Cloud Run env vars to make this permanent.",
            stacklevel=2,
        )
        print(
            f"[auth_store] *** ADMIN_PASSWORD not set — one-time password: {default_password} ***"
        )

    if not _users:
        create_user("admin", default_password, "admin", "Administrator")
        print(f"[auth_store] *** Default admin created — username: admin / password: {default_password} ***")
    else:
        # Ensure an admin account exists with a known password on Cloud Run
        # (GCS may restore old users.json with unknown password hashes)
        # Reset ALL admin-role users + ensure "admin" account exists
        reset_count = 0
        for username, user in _users.items():
            if user.get("role") == "admin":
                salt = secrets.token_hex(16)
                user["salt"] = salt
                user["password_hash"] = _hash_password(default_password, salt)
                reset_count += 1
                print(f"[auth_store] Reset password for admin user '{username}'")

        if "admin" not in _users:
            create_user("admin", default_password, "admin", "Administrator")
            print(f"[auth_store] Created missing 'admin' account")

        _save_users()
        print(f"[auth_store] Loaded {len(_users)} users ({reset_count} admin passwords reset)")


# ── CRUD ─────────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> Optional[dict]:
    """Check credentials. Returns user dict (without password) or None."""
    user = _users.get(username)
    # Always compute hash even for unknown users to prevent timing attacks
    salt = user["salt"] if user else "0" * 32
    hashed = _hash_password(password, salt)
    if not user or not hmac.compare_digest(hashed, user.get("password_hash", "")):
        return None
    return _safe_user(user)


def get_user(username: str) -> Optional[dict]:
    """Return user dict (without password) or None."""
    user = _users.get(username)
    return _safe_user(user) if user else None


def create_user(username: str, password: str, role: str, display_name: str) -> dict:
    """Create a new user. Raises ValueError if username taken or invalid role."""
    if username in _users:
        raise ValueError(f"Username '{username}' already exists")
    if role not in ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {ROLES}")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    salt = secrets.token_hex(16)
    user = {
        "username": username,
        "password_hash": _hash_password(password, salt),
        "salt": salt,
        "role": role,
        "display_name": display_name or username,
        "created_at": time.time(),
    }
    _users[username] = user
    _save_users()
    return _safe_user(user)


def update_user(username: str, updates: dict) -> Optional[dict]:
    """Update user fields (role, display_name, password). Returns updated user or None."""
    user = _users.get(username)
    if not user:
        return None

    if "role" in updates:
        if updates["role"] not in ROLES:
            raise ValueError(f"Invalid role '{updates['role']}'. Must be one of {ROLES}")
        user["role"] = updates["role"]

    if "display_name" in updates:
        user["display_name"] = updates["display_name"]

    if "password" in updates:
        if len(updates["password"]) < 6:
            raise ValueError("Password must be at least 6 characters")
        salt = secrets.token_hex(16)
        user["salt"] = salt
        user["password_hash"] = _hash_password(updates["password"], salt)

    _save_users()
    return _safe_user(user)


def delete_user(username: str) -> bool:
    """Delete a user. Returns True if deleted, False if not found."""
    if username not in _users:
        return False
    del _users[username]
    # Also invalidate any sessions for this user
    tokens_to_remove = [t for t, s in _sessions.items() if s["username"] == username]
    for t in tokens_to_remove:
        del _sessions[t]
    _save_users()
    return True


def list_users() -> list[dict]:
    """Return all users (without passwords)."""
    return [_safe_user(u) for u in _users.values()]


def check_permission(username: str, action: str) -> bool:
    """Check if a user has permission for a given action."""
    user = _users.get(username)
    if not user:
        return False
    role = user.get("role", "viewer")
    perms = ROLE_PERMISSIONS.get(role, set())
    return action in perms


# ── Session management ────────────────────────────────────────────────────────

def save_sessions_to_disk() -> None:
    """Persist active sessions to disk."""
    try:
        data = {token: sess for token, sess in _sessions.items()}
        atomic_write_json(_SESSIONS_FILE, data, indent=2)
    except Exception as e:
        print(f"[auth_store] Could not save sessions: {e}")


def load_sessions_from_disk() -> None:
    """Load sessions from disk at startup."""
    global _sessions
    try:
        if _SESSIONS_FILE.exists():
            raw = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                # Prune expired sessions — must match the 30-day TTL used
                # by get_session_user(); previously this was 24h, which
                # silently invalidated all sessions older than one day.
                now = time.time()
                _sessions = {
                    token: sess for token, sess in raw.items()
                    if now - sess.get("created_at", 0) < 30 * 24 * 3600
                }
                print(f"[auth_store] Loaded {len(_sessions)} sessions from disk")
    except Exception as e:
        print(f"[auth_store] Could not load sessions: {e}")


def create_session(username: str) -> str:
    """Create a session token for a user. Returns the token string."""
    token = secrets.token_hex(32)
    _sessions[token] = {
        "username": username,
        "created_at": time.time(),
    }
    save_sessions_to_disk()
    return token


def get_session_user(token: str) -> Optional[dict]:
    """Look up a session token. Returns user dict or None if invalid/expired."""
    session = _sessions.get(token)
    if not session:
        return None
    # Sessions valid for 30 days
    if time.time() - session["created_at"] > 30 * 24 * 3600:
        del _sessions[token]
        save_sessions_to_disk()
        return None
    return get_user(session["username"])


def invalidate_session(token: str) -> bool:
    """Remove a session token. Returns True if it existed."""
    removed = _sessions.pop(token, None) is not None
    if removed:
        save_sessions_to_disk()
    return removed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_user(user: dict) -> dict:
    """Return user dict without sensitive fields."""
    return {
        "username": user["username"],
        "role": user.get("role", "viewer"),
        "display_name": user.get("display_name", user["username"]),
        "created_at": user.get("created_at"),
    }
