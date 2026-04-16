"""
Authentication & user management routes — RBAC with session tokens.
"""
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

# Usernames: 3-64 chars, alphanumeric + underscore/hyphen only, must start with a letter/digit
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]{2,63}$')

from core.auth_store import (
    authenticate,
    get_user,
    create_user,
    update_user,
    delete_user,
    list_users,
    check_permission,
    create_session,
    get_session_user,
    invalidate_session,
    ROLES,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Dependency: extract current user from token ──────────────────────────────

def _extract_token(request: Request) -> Optional[str]:
    """Extract token from Authorization header or cookie."""
    # Try Authorization: Bearer <token>
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # Try cookie
    return request.cookies.get("mfi_token")


async def get_current_user(request: Request) -> Optional[dict]:
    """FastAPI dependency — returns user dict or None (graceful, doesn't block)."""
    token = _extract_token(request)
    if not token:
        return None
    return get_session_user(token)


async def require_user(request: Request) -> dict:
    """FastAPI dependency — returns user or raises 401."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


async def require_admin(request: Request) -> dict:
    """FastAPI dependency — returns admin user or raises 403."""
    user = await require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# Roles that can run scans / analyst-level operations (analyst, investigator, admin)
_ANALYST_ROLES = {"analyst", "investigator", "admin"}


async def require_analyst(request: Request) -> dict:
    """FastAPI dependency — requires analyst role or above (analyst/investigator/admin)."""
    user = await require_user(request)
    if user["role"] not in _ANALYST_ROLES:
        raise HTTPException(403, "Analyst access required")
    return user


# ── Auth endpoints ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    display_name: str = ""


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    display_name: Optional[str] = None
    password: Optional[str] = None


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    from core.rate_limiter import check_login_rate
    check_login_rate(request)
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = create_session(req.username)
    # Persist session to GCS so it survives container restarts
    try:
        from core.gcs_sync import upload_file
        import asyncio
        asyncio.get_event_loop().run_in_executor(None, upload_file, "sessions.json")
    except Exception:
        pass
    return {
        "token": token,
        "user": user,
    }


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


@router.post("/register")
async def register(req: RegisterRequest, request: Request):
    """Self-registration — creates a viewer account."""
    from core.rate_limiter import check_login_rate
    check_login_rate(request)
    # Validate username format before touching the store
    if not _USERNAME_RE.match(req.username):
        raise HTTPException(
            400,
            "Username must be 3–64 characters, start with a letter or digit, "
            "and contain only letters, digits, hyphens, or underscores.",
        )
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    try:
        user = create_user(
            username=req.username,
            password=req.password,
            role="viewer",
            display_name=req.display_name or req.username,
        )
        token = create_session(req.username)
        return {"token": token, "user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/logout")
async def logout(request: Request):
    token = _extract_token(request)
    if token:
        invalidate_session(token)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return {"user": user}


# ── User management (admin only) ─────────────────────────────────────────────

@router.get("/users")
async def list_all_users(admin: dict = Depends(require_admin)):
    return {"users": list_users()}


@router.post("/users")
async def create_new_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    try:
        user = create_user(
            username=req.username,
            password=req.password,
            role=req.role,
            display_name=req.display_name or req.username,
        )
        return {"user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/users/{username}")
async def update_existing_user(username: str, req: UpdateUserRequest, admin: dict = Depends(require_admin)):
    updates = {}
    if req.role is not None:
        updates["role"] = req.role
    if req.display_name is not None:
        updates["display_name"] = req.display_name
    if req.password is not None:
        updates["password"] = req.password

    if not updates:
        raise HTTPException(400, "No updates provided")

    try:
        user = update_user(username, updates)
        if not user:
            raise HTTPException(404, f"User '{username}' not found")
        return {"user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/users/{username}")
async def delete_existing_user(username: str, admin: dict = Depends(require_admin)):
    if username == admin["username"]:
        raise HTTPException(400, "Cannot delete your own account")
    if not delete_user(username):
        raise HTTPException(404, f"User '{username}' not found")
    return {"ok": True, "deleted": username}


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.patch("/change-password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(require_user)):
    """Let the current user change their own password."""
    # Verify old password
    if not authenticate(user["username"], req.old_password):
        raise HTTPException(400, "Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    try:
        result = update_user(user["username"], {"password": req.new_password})
        if not result:
            raise HTTPException(500, "Failed to update password")
        return {"ok": True, "message": "Password changed successfully"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/roles")
async def get_roles(admin: dict = Depends(require_admin)):
    """Return available roles — admin only, used by user management UI."""
    return {"roles": sorted(ROLES)}
