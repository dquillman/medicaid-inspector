"""
PHI Access Logging Middleware for FastAPI.
Logs all API requests to PHI-relevant paths.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.phi_logger import log_phi_access, PHI_PATH_PATTERNS


class PHIAccessMiddleware(BaseHTTPMiddleware):
    """Log all API requests to PHI-relevant paths to the PHI access logger."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_phi = any(path.startswith(p) for p in PHI_PATH_PATTERNS)

        response = await call_next(request)

        if is_phi and request.method in ("GET", "POST", "PATCH", "DELETE"):
            # Extract user from auth header if available
            uid = "anonymous"
            ah = request.headers.get("authorization", "")
            if ah.startswith("Bearer "):
                from core.auth_store import get_session_user
                su = get_session_user(ah[7:])
                if su:
                    uid = su.get("username", "anonymous")

            # Determine resource type from path
            rt = "provider"
            if "/beneficiary/" in path:
                rt = "beneficiary"
            elif "/cases/" in path:
                rt = "claim"
            elif "/review/" in path:
                rt = "provider"
            elif "/referrals/" in path:
                rt = "referral"
            elif "/evidence/" in path:
                rt = "evidence"

            # Extract resource_id from path segments
            parts = path.rstrip("/").split("/")
            rid = parts[-1] if len(parts) > 3 else path

            log_phi_access(
                user_id=uid,
                action=f"{request.method} {path}",
                resource_type=rt,
                resource_id=rid,
                ip_address=request.client.host if request.client else None,
            )

        return response
