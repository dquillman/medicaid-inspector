"""
Authentication routes — simple email/password auth with JWT tokens.
Users stored in a local JSON file (users.json).
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERS_FILE = Path(__file__).parent.parent / "users.json"
_JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))


def _load_users() -> dict:
    if _USERS_FILE.exists():
        return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_users(users: dict) -> None:
    _USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def _make_token(email: str) -> str:
    """Simple signed token: email.timestamp.signature"""
    ts = str(int(time.time()))
    payload = f"{email}:{ts}"
    sig = hmac.new(_JWT_SECRET.encode(), payload.encode(), "sha256").hexdigest()[:32]
    return f"{payload}:{sig}"


def _verify_token(token: str) -> str | None:
    """Returns email if valid, None otherwise."""
    try:
        parts = token.rsplit(":", 2)
        if len(parts) != 3:
            return None
        email, ts, sig = parts
        payload = f"{email}:{ts}"
        expected = hmac.new(_JWT_SECRET.encode(), payload.encode(), "sha256").hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        # Token valid for 30 days
        if time.time() - int(ts) > 30 * 86400:
            return None
        return email
    except Exception:
        return None


class AuthRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
async def register(req: AuthRequest):
    users = _load_users()
    email = req.email.lower().strip()

    if email in users:
        raise HTTPException(400, "An account with this email already exists")

    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    salt = secrets.token_hex(16)
    hashed = _hash_password(req.password, salt)

    users[email] = {
        "salt": salt,
        "password_hash": hashed,
        "created_at": int(time.time()),
        "plan": "trial",
    }
    _save_users(users)

    token = _make_token(email)
    return {"email": email, "token": token, "plan": "trial"}


@router.post("/login")
async def login(req: AuthRequest):
    users = _load_users()
    email = req.email.lower().strip()

    if email not in users:
        raise HTTPException(401, "Invalid email or password")

    user = users[email]
    hashed = _hash_password(req.password, user["salt"])

    if not hmac.compare_digest(hashed, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    token = _make_token(email)
    return {"email": email, "token": token, "plan": user.get("plan", "trial")}


@router.get("/me")
async def me(token: str = ""):
    email = _verify_token(token)
    if not email:
        raise HTTPException(401, "Invalid or expired token")

    users = _load_users()
    user = users.get(email, {})
    return {
        "email": email,
        "plan": user.get("plan", "trial"),
        "created_at": user.get("created_at"),
    }
