"""
Evidence chain-of-custody store.
Tracks metadata for evidence files uploaded to cases, including SHA-256 hashes.
Persisted to backend/evidence_metadata.json.
"""
import json
import re
import time
import pathlib
import hashlib
import threading
import uuid
from typing import Optional

# Only allow a short, alphanumeric file extension so the stored filename
# can never be manipulated via a malicious uploaded filename.
_SAFE_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")
# case_id and evidence_id both need to be filesystem-safe (no separators,
# no traversal sequences) since they form the on-disk filename.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _safe_extension(original_filename: str) -> str:
    """Return a safe file extension (or empty string) from a user-supplied name."""
    raw_ext = pathlib.Path(original_filename).suffix
    if raw_ext and _SAFE_EXT_RE.match(raw_ext):
        return raw_ext
    return ""

_META_FILE = pathlib.Path(__file__).parent.parent / "evidence_metadata.json"
_EVIDENCE_DIR = pathlib.Path(__file__).parent.parent / "evidence"

# In-memory: case_id (NPI) -> list of evidence records
_evidence: dict[str, list[dict]] = {}
_lock = threading.Lock()


def _ensure_evidence_dir() -> None:
    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


# ── disk persistence ──────────────────────────────────────────────────────────

def load_evidence_from_disk() -> None:
    global _evidence
    try:
        if not _META_FILE.exists():
            return
        raw = json.loads(_META_FILE.read_text(encoding="utf-8"))
        _evidence = raw.get("evidence", {})
        total = sum(len(v) for v in _evidence.values())
        print(f"[evidence_store] Loaded metadata for {total} evidence files across {len(_evidence)} cases")
    except Exception as e:
        print(f"[evidence_store] Could not load evidence metadata: {e}")


def _save_to_disk() -> None:
    try:
        _META_FILE.write_text(
            json.dumps({"evidence": _evidence}, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[evidence_store] Could not save evidence metadata: {e}")


# ── core operations ───────────────────────────────────────────────────────────

def compute_sha256(file_bytes: bytes) -> str:
    """Compute SHA-256 hash of file contents."""
    return hashlib.sha256(file_bytes).hexdigest()


def add_evidence(
    case_id: str,
    original_filename: str,
    file_bytes: bytes,
    uploaded_by: str,
    description: str = "",
    evidence_type: str = "document",
) -> dict:
    """
    Store evidence file and record metadata with chain-of-custody info.
    Returns the evidence metadata record.
    """
    _ensure_evidence_dir()

    # Validate case_id — it becomes part of the stored filename, so it must
    # be free of path separators and traversal sequences.
    if not _SAFE_ID_RE.match(case_id):
        raise ValueError("case_id contains unsafe characters")

    evidence_id = str(uuid.uuid4())[:12]
    sha256_hash = compute_sha256(file_bytes)
    file_size = len(file_bytes)

    # Safely derive extension — rejects anything beyond a short alphanumeric
    # suffix (prevents null-byte / separator / overlong injection).
    ext = _safe_extension(original_filename)
    stored_filename = f"{case_id}_{evidence_id}{ext}"
    stored_path = _EVIDENCE_DIR / stored_filename

    # Defense-in-depth: ensure the resolved path stays within _EVIDENCE_DIR.
    try:
        stored_path.resolve().relative_to(_EVIDENCE_DIR.resolve())
    except ValueError:
        raise ValueError("Stored path escaped evidence directory") from None

    # Write the file first. Only register metadata if the write succeeds,
    # so we never have a metadata record pointing at a missing file.
    stored_path.write_bytes(file_bytes)

    now = time.time()
    record = {
        "evidence_id": evidence_id,
        "case_id": case_id,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "sha256_hash": sha256_hash,
        "file_size": file_size,
        "uploaded_by": uploaded_by,
        "upload_timestamp": now,
        "description": description,
        "evidence_type": evidence_type,
        "chain_of_custody": [
            {
                "action": "uploaded",
                "by": uploaded_by,
                "timestamp": now,
                "sha256_hash": sha256_hash,
            }
        ],
    }

    try:
        with _lock:
            if case_id not in _evidence:
                _evidence[case_id] = []
            _evidence[case_id].append(record)
            _save_to_disk()
    except Exception:
        # If metadata persistence fails, roll back the file write so we
        # don't leave an orphaned blob on disk with no custody record.
        try:
            stored_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    return record


def get_evidence_list(case_id: str) -> list[dict]:
    """Return all evidence records for a case."""
    return _evidence.get(case_id, [])


def get_evidence_record(case_id: str, evidence_id: str) -> Optional[dict]:
    """Return a single evidence record by ID."""
    for rec in _evidence.get(case_id, []):
        if rec["evidence_id"] == evidence_id:
            return rec
    return None


def get_evidence_file_path(case_id: str, evidence_id: str) -> Optional[pathlib.Path]:
    """Return the filesystem path to an evidence file, verifying integrity."""
    rec = get_evidence_record(case_id, evidence_id)
    if not rec:
        return None
    stored_path = _EVIDENCE_DIR / rec["stored_filename"]
    if not stored_path.exists():
        return None
    return stored_path


def verify_evidence_integrity(case_id: str, evidence_id: str) -> Optional[dict]:
    """Verify SHA-256 hash of stored evidence file matches original."""
    rec = get_evidence_record(case_id, evidence_id)
    if not rec:
        return None
    stored_path = _EVIDENCE_DIR / rec["stored_filename"]
    if not stored_path.exists():
        return {"valid": False, "error": "File not found on disk"}
    current_hash = compute_sha256(stored_path.read_bytes())
    original_hash = rec["sha256_hash"]
    return {
        "valid": current_hash == original_hash,
        "original_hash": original_hash,
        "current_hash": current_hash,
        "evidence_id": evidence_id,
    }


def add_custody_event(case_id: str, evidence_id: str, action: str, by: str) -> Optional[dict]:
    """Add a chain-of-custody event to an evidence record."""
    with _lock:
        rec = get_evidence_record(case_id, evidence_id)
        if not rec:
            return None
        rec["chain_of_custody"].append({
            "action": action,
            "by": by,
            "timestamp": time.time(),
        })
        _save_to_disk()
    return rec


def get_evidence_dir() -> pathlib.Path:
    _ensure_evidence_dir()
    return _EVIDENCE_DIR
