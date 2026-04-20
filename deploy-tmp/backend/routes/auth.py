"""
Authentication routes — Firebase Auth token verification.
Users are managed through admin-core; this backend only verifies tokens.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request

from core.firebase_auth import verify_token, get_user_role, check_permission, ROLES

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Dependencies ─────────────────────────────────────────────────────────────

def _extract_token(request: Request) -> Optional[str]:
    """Extract Firebase ID token from Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


async def get_current_user(request: Request) -> Optional[dict]:
    """FastAPI dependency — returns user dict or None."""
    token = _extract_token(request)
    if not token:
        return None
    decoded = verify_token(token)
    if not decoded:
        return None
    uid = decoded["uid"]
    email = decoded.get("email", "")
    role = get_user_role(uid, email)
    return {
        "uid": uid,
        "email": email,
        "username": email,  # backwards compat for existing route code
        "role": role,
        "display_name": decoded.get("name", email),
    }


async def require_user(request: Request) -> dict:
    """FastAPI dependency — returns user or raises 401."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


async def require_admin(request: Request) -> dict:
    """FastAPI dependency — returns admin user or raises 403."""
    user = await require_user(request)
    if user["role"] not in ("admin", "super-admin"):
        raise HTTPException(403, "Admin access required")
    return user


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return {"user": user}


@router.get("/roles")
async def get_roles():
    """Return available roles (public, used by admin UI)."""
    return {"roles": sorted(ROLES)}
