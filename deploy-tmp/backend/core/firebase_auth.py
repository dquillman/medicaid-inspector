"""
Firebase Authentication — verifies ID tokens from the shared admin-core Firebase project.
Replaces custom session-based auth with Firebase Auth token verification.
"""
import os
import logging
from typing import Optional

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials, firestore

logger = logging.getLogger(__name__)

_app: Optional[firebase_admin.App] = None
_db = None

# App-level RBAC permissions (kept from original auth_store)
ROLES = {"admin", "super-admin", "investigator", "analyst", "viewer", "user"}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {
        "read_providers", "read_reports", "read_review",
        "read_anomalies", "read_network", "read_summary",
    },
    "user": {
        "read_providers", "read_reports", "read_review",
        "read_anomalies", "read_network", "read_summary",
    },
    "analyst": {
        "read_providers", "read_reports", "read_review",
        "read_anomalies", "read_network", "read_summary",
        "run_scan", "run_smart_scan", "run_rescore",
        "generate_reports", "run_ml_training", "export_data",
    },
    "investigator": {
        "read_providers", "read_reports", "read_review",
        "read_anomalies", "read_network", "read_summary",
        "run_scan", "run_smart_scan", "run_rescore",
        "generate_reports", "run_ml_training", "export_data",
        "modify_review", "assign_review", "add_notes",
        "log_hours", "bulk_update_review",
    },
    "admin": {
        "read_providers", "read_reports", "read_review",
        "read_anomalies", "read_network", "read_summary",
        "run_scan", "run_smart_scan", "run_rescore",
        "generate_reports", "run_ml_training", "export_data",
        "modify_review", "assign_review", "add_notes",
        "log_hours", "bulk_update_review",
        "manage_users", "manage_alert_rules",
        "delete_data", "reset_scan",
    },
    "super-admin": {
        "read_providers", "read_reports", "read_review",
        "read_anomalies", "read_network", "read_summary",
        "run_scan", "run_smart_scan", "run_rescore",
        "generate_reports", "run_ml_training", "export_data",
        "modify_review", "assign_review", "add_notes",
        "log_hours", "bulk_update_review",
        "manage_users", "manage_alert_rules",
        "delete_data", "reset_scan",
    },
}

BOOTSTRAP_ADMIN_EMAIL = "dquillman2112@gmail.com"

# Shared Firebase project ID (admin-core hub used by all apps)
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "exam-coach-ai-platform")


def init_firebase() -> None:
    """Initialize Firebase Admin SDK. Uses GOOGLE_APPLICATION_CREDENTIALS env var or default credentials."""
    global _app, _db
    if _app is not None:
        return
    try:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        options = {"projectId": FIREBASE_PROJECT_ID}
        if cred_path:
            cred = credentials.Certificate(cred_path)
            _app = firebase_admin.initialize_app(cred, options)
        else:
            # Use Application Default Credentials (works on Cloud Run)
            _app = firebase_admin.initialize_app(options=options)
        _db = firestore.client()
        logger.info(f"[firebase_auth] Firebase Admin SDK initialized (project={FIREBASE_PROJECT_ID})")
    except Exception as e:
        logger.error(f"[firebase_auth] Failed to initialize Firebase: {e}")
        raise


def get_firestore_db():
    """Return Firestore client."""
    if _db is None:
        init_firebase()
    return _db


def verify_token(id_token: str) -> Optional[dict]:
    """
    Verify a Firebase ID token.
    Returns decoded token dict with uid, email, etc. or None if invalid.
    """
    if _app is None:
        init_firebase()
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return decoded
    except firebase_auth.InvalidIdTokenError:
        return None
    except firebase_auth.ExpiredIdTokenError:
        return None
    except Exception as e:
        logger.warning(f"[firebase_auth] Token verification failed: {e}")
        return None


def get_user_role(uid: str, email: str = "") -> str:
    """
    Look up user role from Firestore /users/{uid}.
    Falls back to 'admin' for bootstrap admin email, 'user' otherwise.
    """
    db = get_firestore_db()
    try:
        doc = db.collection("users").document(uid).get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("role", "user")
    except Exception as e:
        logger.warning(f"[firebase_auth] Could not fetch role for {uid}: {e}")

    # Bootstrap: grant admin to known admin email
    if email == BOOTSTRAP_ADMIN_EMAIL:
        return "admin"
    return "user"


def check_permission(role: str, action: str) -> bool:
    """Check if a role has permission for a given action."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return action in perms
