"""Smoke the COPIED, marked local refresh stage; never launch a network server.

Run only after validate_refresh finishes. All auth is synthetic and all writes
remain under the stage. Public output contains aggregate counts/statuses only.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
import secrets
import sys
import traceback


def validate_evaluation_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("Evaluation name must be a single safe directory basename")
    return value


def smoke(stage: Path, evaluation_name: str = "evaluation") -> dict:
    evaluation_name = validate_evaluation_name(evaluation_name)
    from validate_refresh import prepare_offline

    # Refuse copied operator identities before importing any auth/startup code.
    for name in (".env", "users.json", "sessions.json", "app.db", "app.db-wal", "app.db-shm"):
        if (stage / name).exists():
            raise ValueError("Stage must not contain operator authentication state")
    completed = json.loads((stage / "refresh-validation-report.json").read_text(encoding="utf-8"))
    if completed.get("status") != "complete":
        raise ValueError("Completed local refresh report required")
    if not (stage / "prescan_slim.json").is_file():
        raise ValueError("Refreshed slim cache required")

    password = secrets.token_urlsafe(32)
    os.environ.update(ADMIN_PASSWORD=password, APP_VERSION="local-stage-validation",
                      K_SERVICE="local-stage-smoke", EVIDENCE_ALLOW_LOCAL_ONLY="1")
    prepare_offline(stage)

    # Isolate login/SQLite side effects from even the refreshed stage artifacts.
    auth_root = stage / "scratch" / ("smoke-auth-" + secrets.token_hex(6))
    auth_root.mkdir()
    from core import auth_store, database
    auth_store._USERS_FILE = auth_root / "users.json"
    auth_store._SESSIONS_FILE = auth_root / "sessions.json"
    auth_store._ADMIN_INIT_FLAG = auth_root / ".admin_initialized"
    database._DB_PATH = auth_root / "app.db"
    from fastapi.testclient import TestClient
    import main
    if Path(main.__file__).resolve().parent != stage:
        raise ValueError("Application imported outside isolated stage")
    if not main.BACKGROUND_JOBS_DISABLED:
        raise ValueError("Background jobs must be disabled")

    report = {"status": "complete", "scope": "local staged API only; no cloud/IAM or independent fraud validation",
              "routes": {}, "counts": {}}
    with TestClient(main.app, raise_server_exceptions=True) as client:
        def get(label, path, headers=None):
            response = client.get(path, headers=headers or {})
            report["routes"][label] = response.status_code
            if response.status_code != 200:
                raise RuntimeError("Staged route failed: " + label)
            return response.json()

        health = get("health", "/health")
        if health.get("status") != "healthy":
            raise RuntimeError("Health status invalid")
        methods = get("public_methods", "/api/methods")
        report["counts"]["screening_signals"] = methods.get("signal_count", 0)
        denied = client.get("/api/admin/data-quality")
        report["routes"]["admin_unauthenticated"] = denied.status_code
        if denied.status_code not in (401, 403):
            raise RuntimeError("Admin route must require authentication")
        login = client.post("/api/auth/login", json={"username": "admin", "password": password})
        report["routes"]["synthetic_login"] = login.status_code
        if login.status_code != 200 or not login.json().get("token"):
            raise RuntimeError("Synthetic login failed")
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        sampled = client.post("/api/admin/data-quality/run?sample_limit=5000", headers=headers)
        report["routes"]["sampled_data_quality"] = sampled.status_code
        sample_result = sampled.json()
        if sampled.status_code != 200 or sample_result.get("status") != "complete":
            raise RuntimeError("Staged source validation did not complete")
        # Preserve capped raw diagnostics privately; public report below remains
        # aggregate-only. Never overwrite an earlier sampled evidence snapshot.
        diagnostic_path = auth_root / "source-quality-private.json"
        diagnostic_path.write_text(json.dumps(sample_result, indent=2, default=str), encoding="utf-8")
        report["sampled_source_quality"] = {key: sample_result.get(key) for key in (
            "sample_size", "valid_records", "invalid_records", "quality_score", "failures",
            "beneficiary_count_states", "duplicate_source_grain_rows_in_sample",
            "servicing_identity_states", "source_code_states", "review_flags",
            "sample_seed", "sample_sha256", "code_system_mismatch_records")}
        quality = get("admin_data_quality", "/api/admin/data-quality", headers)
        validation = (quality.get("derived_artifact") or {}).get("validation") or {}
        report["derived_provenance_usable"] = bool(validation.get("usable"))
        if not report["derived_provenance_usable"]:
            raise RuntimeError("Derived provenance incompatible")
        ranking = get("brain_top50", "/api/fraud-brain/top?limit=50&refresh=true", headers)
        rows = ranking.get("top") or []
        report["counts"]["ranked_sample"] = len(rows)
        report["counts"]["providers_evaluated"] = ranking.get("providers_evaluated", 0)
        if not rows or not report["counts"]["providers_evaluated"]:
            raise RuntimeError("Refreshed ranking is empty")

        # The list endpoint otherwise performs NPPES enrichment. Select one
        # already-enriched, eligible cached row; never exercise that branch.
        from core.store import get_prescanned
        from core.perse_store import is_on_excluded_page
        from core.identity_contract import is_valid_npi
        candidate = next((row for row in get_prescanned()
                          if row.get("nppes") and is_valid_npi(row.get("npi"))
                          and not is_on_excluded_page(row.get("npi", ""))), None)
        if candidate:
            listing = get("limited_cached_provider_list",
                          "/api/providers?limit=1&search=" + candidate["npi"], headers)
            report["counts"]["listed_cached_providers"] = len(listing.get("providers") or [])
            if report["counts"]["listed_cached_providers"] != 1:
                raise RuntimeError("Expected one cached provider")
            network = get("network_identity_guard", "/api/network/" + candidate["npi"], headers)
            if not all(is_valid_npi(node.get("id")) for node in network.get("nodes", [])):
                raise RuntimeError("Network exposed an ineligible identity")
            report["counts"]["checked_network_nodes"] = len(network.get("nodes", []))
        else:
            report["routes"]["limited_cached_provider_list"] = "skipped_no_safe_enriched_row"

        # Freeze actual ranking without inventing outcomes. Private identities
        # and scores remain separate from unresolved, blinded review records.
        evaluation = stage / evaluation_name
        evaluation.mkdir(exist_ok=False)
        from services.evaluation import freeze_ranking
        manifest = freeze_ranking(rows, snapshot_id="local-stage-" + secrets.token_hex(12),
                                  provenance={"derived_manifest": validation.get("provenance"),
                                              "generated_at": datetime.now(timezone.utc).isoformat()}, k=50)
        with (evaluation / "private_manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
        # Independent review needs factual source material, without model cues.
        # Provider identity is necessary for external checks; ranking, scores,
        # detector flags, prior case decisions and generated allegations stay private.
        mapping = {row["npi"]: row["case_id"] for row in manifest["private_rows"]}
        packets = evaluation / "factual_packets"
        packets.mkdir()
        from validate_refresh import iter_provider_rows
        packet_count = 0
        for provider in iter_provider_rows(stage / "prescan_cache.json"):
            case_id = mapping.get(provider.get("npi"))
            if not case_id:
                continue
            packet = {
                "case_id": case_id,
                "subject": {"npi": provider.get("npi"), "provider_name": provider.get("provider_name"),
                            "nppes": provider.get("nppes"), "specialty": provider.get("specialty")},
                "published_aggregates": {key: provider.get(key) for key in (
                    "total_paid", "total_claims", "total_beneficiaries", "active_months", "first_month", "last_month")},
                "hcpcs": provider.get("hcpcs") or [], "timeline": provider.get("timeline") or [],
                "limitations": ["Historical public aggregates; not claim lines or proof of fraud.",
                                "Beneficiary counts are summed cells, not unique people.",
                                "Source retrieval date and current enrollment must be independently verified."],
            }
            with (packets / (case_id + ".json")).open("x", encoding="utf-8") as stream:
                json.dump(packet, stream, indent=2, allow_nan=False)
            packet_count += 1
        if packet_count != manifest["sample_size"]:
            raise RuntimeError("Frozen sample evidence packet inventory incomplete")
        report["counts"]["factual_review_packets"] = packet_count
        blinded = {"snapshot_id": manifest["snapshot_id"], "manifest_sha256": manifest["manifest_sha256"],
                   "instruction": "Independent evidence review required; withhold ranks, model scores and prior conclusions. Subject identity supports external verification.",
                   "adjudications": [{"case_id": case_id, "outcome": "unresolved", "reviewer": "",
                                       "review_date": "", "evidence_reference": ""}
                                      for case_id in manifest["blinded_order"]]}
        with (evaluation / "blinded_review.json").open("x", encoding="utf-8") as stream:
            json.dump(blinded, stream, indent=2)
        report["counts"]["unresolved_evaluation_cases"] = manifest["sample_size"]
        report["evaluation_directory"] = str(evaluation)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-root", required=True, type=Path)
    parser.add_argument("--evaluation-name", default="evaluation", type=validate_evaluation_name)
    args = parser.parse_args()
    from validate_refresh import validate_stage
    try:
        stage = validate_stage(args.stage_root)
    except Exception as error:
        print("Staging guard rejected: " + type(error).__name__, flush=True)
        return 1
    sys.path.insert(0, str(stage))
    os.chdir(stage)
    public = sys.stdout
    with (stage / "smoke-private.log").open("a", encoding="utf-8") as private:
        with redirect_stdout(private), redirect_stderr(private):
            logging.basicConfig(stream=private, level=logging.WARNING, force=True)
            try:
                result = smoke(stage, args.evaluation_name)
                (stage / "smoke-validation-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            except BaseException as error:
                traceback.print_exc()
                public.write("Staged smoke failed (" + type(error).__name__ + "); details retained privately\n")
                public.flush()
                return 1
    public.write(json.dumps(result, separators=(",", ":")) + "\n")
    public.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
