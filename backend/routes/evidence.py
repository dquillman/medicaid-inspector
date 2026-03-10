"""
Evidence chain-of-custody API routes.
Upload, list, download, and verify evidence files for cases.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.responses import FileResponse

from core.evidence_store import (
    add_evidence,
    get_evidence_list,
    get_evidence_record,
    get_evidence_file_path,
    verify_evidence_integrity,
    add_custody_event,
)
from core.phi_logger import log_phi_access
from routes.auth import require_user, get_current_user

router = APIRouter(prefix="/api/cases", tags=["evidence"], dependencies=[Depends(require_user)])


@router.post("/{case_id}/evidence")
async def upload_evidence(
    case_id: str,
    request: Request,
    file: UploadFile = File(...),
    description: str = Form(""),
    evidence_type: str = Form("document"),
    user: dict = Depends(require_user),
):
    """Upload an evidence file for a case. Computes and stores SHA-256 hash."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(400, "Empty file")

    # Max 50MB
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large — maximum 50MB")

    record = add_evidence(
        case_id=case_id,
        original_filename=file.filename,
        file_bytes=file_bytes,
        uploaded_by=user.get("username", "unknown"),
        description=description,
        evidence_type=evidence_type,
    )

    # Log PHI access
    log_phi_access(
        user_id=user.get("username", "unknown"),
        action="evidence_uploaded",
        resource_type="evidence",
        resource_id=f"{case_id}/{record['evidence_id']}",
        ip_address=request.client.host if request.client else None,
    )

    return record


@router.get("/{case_id}/evidence")
async def list_evidence(case_id: str):
    """List all evidence files for a case with metadata."""
    items = get_evidence_list(case_id)
    return {
        "case_id": case_id,
        "evidence": items,
        "total": len(items),
    }


@router.get("/{case_id}/evidence/{evidence_id}/download")
async def download_evidence(
    case_id: str,
    evidence_id: str,
    request: Request,
    user: dict = Depends(require_user),
):
    """Download an evidence file. Logs chain-of-custody access event."""
    record = get_evidence_record(case_id, evidence_id)
    if not record:
        raise HTTPException(404, f"Evidence {evidence_id} not found for case {case_id}")

    file_path = get_evidence_file_path(case_id, evidence_id)
    if not file_path or not file_path.exists():
        raise HTTPException(404, "Evidence file not found on disk")

    # Add custody event
    add_custody_event(
        case_id, evidence_id,
        action="downloaded",
        by=user.get("username", "unknown"),
    )

    # Log PHI access
    log_phi_access(
        user_id=user.get("username", "unknown"),
        action="evidence_downloaded",
        resource_type="evidence",
        resource_id=f"{case_id}/{evidence_id}",
        ip_address=request.client.host if request.client else None,
    )

    return FileResponse(
        path=str(file_path),
        filename=record["original_filename"],
        media_type="application/octet-stream",
    )


@router.get("/{case_id}/evidence/{evidence_id}/verify")
async def verify_evidence(case_id: str, evidence_id: str):
    """Verify SHA-256 hash integrity of stored evidence file."""
    result = verify_evidence_integrity(case_id, evidence_id)
    if result is None:
        raise HTTPException(404, f"Evidence {evidence_id} not found for case {case_id}")
    return result


@router.get("/{case_id}/evidence/{evidence_id}/custody")
async def evidence_custody_chain(case_id: str, evidence_id: str):
    """Get the full chain-of-custody log for an evidence file."""
    record = get_evidence_record(case_id, evidence_id)
    if not record:
        raise HTTPException(404, f"Evidence {evidence_id} not found for case {case_id}")
    return {
        "evidence_id": evidence_id,
        "case_id": case_id,
        "original_filename": record["original_filename"],
        "sha256_hash": record["sha256_hash"],
        "chain_of_custody": record["chain_of_custody"],
    }
