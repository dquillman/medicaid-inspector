"""
Role-Based Access Control (RBAC) store.
Manages users, roles, permissions, and session tokens.
Persists users to backend/users.json.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
import pathlib
from typing import Optional

from core.safe_io import atomic_write_json

_USERS_FILE = pathlib.Path(__file__).parent.parent / "users.json"
_SESSIONS_FILE = pathlib.Path(__file__).parent.parent / "sessions.json"
_ADMIN_INIT_FLAG = pathlib.Path(__file__).parent.parent / ".admin_initialized"

# Session lifetime: a 30-day absolute cap plus a sliding idle timeout. A token
# unused for longer than the idle window is rejected even if it's within the
# 30 days, limiting the exposure of a leaked token.
_SESSION_ABSOLUTE_TTL = 30 * 24 * 3600
_SESSION_IDLE_TTL = int(os.environ.get("MFI_SESSION_IDLE_HOURS", "12")) * 3600
# Only re-persist last_seen when it advances by this much, to avoid a disk
# write on every authenticated request.
_LAST_SEEN_PERSIST_INTERVAL = 60

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
    """Load users and sessions from disk at startup. Guarantee an 'admin' account exists.

    Policy (fixes prior lock-out bug — do NOT revert):
    - If ADMIN_PASSWORD env var is set: (re)sync the 'admin' account to that
      password on every boot. Other admin-role users are NEVER touched.
    - If ADMIN_PASSWORD env var is NOT set: existing admin passwords are
      preserved across restarts. An 'admin' account is created with a one-time
      random password only if it does not already exist.
    """
    import os
    _load_users()
    load_sessions_from_disk()

    admin_password = os.environ.get("ADMIN_PASSWORD")

    def _set_admin_password(username: str, password: str) -> None:
        salt = secrets.token_hex(16)
        _users[username]["salt"] = salt
        _users[username]["password_hash"] = _hash_password(password, salt)
        _users[username]["role"] = "admin"

    # Case 1: no users at all — cold bootstrap
    if not _users:
        if not admin_password:
            admin_password = secrets.token_urlsafe(16)
            print(
                f"[auth_store] *** Cold bootstrap — one-time admin password: {admin_password}. "
                f"Set ADMIN_PASSWORD env var in Cloud Run to make this permanent. ***"
            )
        create_user("admin", admin_password, "admin", "Administrator")
        print("[auth_store] Bootstrapped admin account (username: admin)")
        return

    # Case 2: users exist, ADMIN_PASSWORD is set — sync canonical 'admin' only
    if admin_password:
        if "admin" in _users:
            _set_admin_password("admin", admin_password)
            print("[auth_store] Synced 'admin' password from ADMIN_PASSWORD env var")
        else:
            create_user("admin", admin_password, "admin", "Administrator")
            print("[auth_store] Created 'admin' account from ADMIN_PASSWORD env var")
        _save_users()
        print(f"[auth_store] Loaded {len(_users)} users")
        return

    # Case 3: users exist, ADMIN_PASSWORD not set — preserve existing hashes.
    # Only create 'admin' if it is missing, so the operator always has a path in.
    if "admin" not in _users:
        admin_password = secrets.token_urlsafe(16)
        create_user("admin", admin_password, "admin", "Administrator")
        print(
            f"[auth_store] *** Created missing 'admin' with one-time password: {admin_password}. "
            f"Set ADMIN_PASSWORD env var and restart for a stable password. ***"
        )
    print(f"[auth_store] Loaded {len(_users)} users (existing admin hashes preserved)")


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
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    salt = secrets.token_hex(16)
    user = {
        "username": username,
        "password_hash": _hash_password(password, salt),
        "salt": salt,
        "role": role,
        "display_name": display_name or username,
        "created_at": time.time(),
        "auth_provider": "local",
    }
    _users[username] = user
    _save_users()
    return _safe_user(user)


def create_or_get_google_user(email: str, display_name: str, default_role: str = "viewer") -> dict:
    """Return an existing user keyed by email, or create a passwordless Google user.

    Google users have no password_hash/salt — `authenticate()` will never return
    them, so they can only sign in via the Google ID-token flow.
    """
    existing = _users.get(email)
    if existing:
        return _safe_user(existing)

    if default_role not in ROLES:
        raise ValueError(f"Invalid role '{default_role}'. Must be one of {ROLES}")

    user = {
        "username": email,
        "password_hash": "",
        "salt": "",
        "role": default_role,
        "display_name": display_name or email,
        "created_at": time.time(),
        "auth_provider": "google",
    }
    _users[email] = user
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

    password_changed = False
    if "password" in updates:
        if len(updates["password"]) < 8:
            raise ValueError("Password must be at least 8 characters")
        salt = secrets.token_hex(16)
        user["salt"] = salt
        user["password_hash"] = _hash_password(updates["password"], salt)
        password_changed = True

    _save_users()
    # A password change must not leave old sessions valid — force re-login.
    if password_changed:
        invalidate_user_sessions(username)
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
    now = time.time()
    _sessions[token] = {
        "username": username,
        "created_at": now,
        "last_seen": now,
    }
    save_sessions_to_disk()
    return token


def get_session_user(token: str) -> Optional[dict]:
    """Look up a session token. Returns user dict or None if invalid/expired.

    Enforces both a 30-day absolute cap and a sliding idle timeout, and
    refreshes last_seen (persisting lazily) so an active session stays alive
    while an abandoned one expires.
    """
    session = _sessions.get(token)
    if not session:
        return None
    now = time.time()
    last_seen = session.get("last_seen", session.get("created_at", now))
    if (now - session.get("created_at", now) > _SESSION_ABSOLUTE_TTL
            or now - last_seen > _SESSION_IDLE_TTL):
        del _sessions[token]
        save_sessions_to_disk()
        return None
    user = get_user(session["username"])
    if user is None:
        # User was deleted out from under an active session.
        del _sessions[token]
        save_sessions_to_disk()
        return None
    # Slide the idle window; only touch disk when it advances meaningfully.
    if now - last_seen >= _LAST_SEEN_PERSIST_INTERVAL:
        session["last_seen"] = now
        save_sessions_to_disk()
    else:
        session["last_seen"] = now
    return user


def invalidate_user_sessions(username: str) -> int:
    """Remove all sessions for a user. Returns the count removed.

    Called when a user's password changes so old tokens can't outlive the
    credential they were issued against.
    """
    tokens = [t for t, s in _sessions.items() if s.get("username") == username]
    for t in tokens:
        del _sessions[t]
    if tokens:
        save_sessions_to_disk()
    return len(tokens)


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
