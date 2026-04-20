"""
Whistleblower URLs API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.whistleblower_store import get_all_urls, update_url, reset_url

router = APIRouter(prefix="/api/whistleblower", tags=["whistleblower"])


class UpdateUrlBody(BaseModel):
    url: str


@router.get("/urls")
def list_urls():
    """Return all state whistleblower URLs."""
    return get_all_urls()


@router.patch("/urls/{code}")
def patch_url(code: str, body: UpdateUrlBody):
    """Update a state's whistleblower URL."""
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")
    try:
        return update_url(code, url)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/urls/{code}")
def delete_url_override(code: str):
    """Reset a state's URL back to default."""
    try:
        return reset_url(code)
    except ValueError as e:
        raise HTTPException(404, str(e))
