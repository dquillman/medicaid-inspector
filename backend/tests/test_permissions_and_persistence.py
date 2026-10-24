"""
Regression tests (audit 2026-10-24, item 10):
  - evidence upload and case mutations must require the 'investigator' role,
    matching every other comparable write (referral updates, review status).
  - referral_workflow._save_to_disk must be a crash-safe atomic write, not a
    raw write_text that can leave a truncated file.
"""
import io
import json

import core.referral_workflow as referral_workflow


def _create_viewer_user(client, auth_headers, username: str) -> dict:
    resp = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": username, "password": "viewerpass123", "role": "viewer",
              "display_name": "Viewer"},
    )
    assert resp.status_code == 200, resp.text
    login = client.post("/api/auth/login", json={"username": username, "password": "viewerpass123"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_evidence_upload_refuses_plain_user_role(client, auth_headers):
    viewer_headers = _create_viewer_user(client, auth_headers, "viewer_evidence_test")
    resp = client.post(
        "/api/cases/1234567890/evidence",
        headers=viewer_headers,
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 403


def test_case_mutations_refuse_plain_user_role(client, auth_headers):
    viewer_headers = _create_viewer_user(client, auth_headers, "viewer_cases_test")
    resp = client.patch(
        "/api/cases/1234567890/priority",
        headers=viewer_headers,
        json={"priority": "high"},
    )
    assert resp.status_code == 403


def test_referral_save_writes_via_atomic_tmp_replace(tmp_path, monkeypatch):
    fake_file = tmp_path / "referrals.json"
    monkeypatch.setattr(referral_workflow, "_REFERRALS_FILE", fake_file)
    monkeypatch.setattr(referral_workflow, "_referrals", [{"id": 1, "npi": "1234567890"}])

    referral_workflow._save_to_disk()

    assert fake_file.exists()
    data = json.loads(fake_file.read_text(encoding="utf-8"))
    assert data["referrals"][0]["npi"] == "1234567890"
    # No leftover temp file from the atomic-write pattern.
    leftovers = list(tmp_path.glob(".*referrals*.tmp"))
    assert leftovers == []
