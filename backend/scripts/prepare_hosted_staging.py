"""Generate isolated hosted-staging configuration locally. Never calls a cloud CLI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re


def prepare(project: str, bucket: str, output: Path, *, shared_project: bool = False, service: str = "mfi-api-staging"):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise ValueError("Invalid project ID")
    if shared_project:
        if project != "medicaid-inspector":
            raise ValueError("Shared-project mode is scoped explicitly to medicaid-inspector")
    elif "stag" not in project or project == "medicaid-inspector":
        raise ValueError("A staging-named project is required unless --shared-project is explicit")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,60}[a-z0-9]", service) or "stag" not in service:
        raise ValueError("An explicitly staging-named service is required")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,60}[a-z0-9]", bucket) or "stag" not in bucket:
        raise ValueError("An explicitly staging-named bucket is required")
    if service == "medicaid-inspector-api" or bucket == "medicaid-inspector-data":
        raise ValueError("Production targets are forbidden")
    if output.exists():
        raise ValueError("Output must be a new directory; existing configurations are never replaced")
    env = {"GCS_BUCKET": bucket, "MFI_DISABLE_BACKGROUND_JOBS": "1", "MFI_EXPECTED_MAX_INSTANCES": "1",
           "APP_VERSION": "staging", "PARQUET_URL": f"https://storage.googleapis.com/{bucket}/public-aggregate-source.parquet",
           "LOCAL_PARQUET_PATH": "/app/data/medicaid-provider-spending.parquet",
           "HAL_QCODE_DIR": "", "HAL_URL": "", "HAL_TOKEN": "", "ANTHROPIC_API_KEY": "",
           "OPENAI_API_KEY": "", "SAM_API_KEY": "", "MMIS_ENDPOINT_URL": "", "MMIS_API_KEY": "",
           "NARRATIVE_LLM_ENABLED": "false", "SMTP_HOST": "", "SMTP_PASS": ""}
    firebase = {"hosting": {"public": "frontend/dist", "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
                "rewrites": [{"source": "/api/**", "run": {"serviceId": service, "region": "us-central1"}},
                             {"source": "**", "destination": "/index.html"}],
                "headers": [{"source": "**", "headers": [{"key": "X-Robots-Tag", "value": "noindex, nofollow"},
                                                               {"key": "Cache-Control", "value": "no-store"}]}]}}
    if shared_project:
        # Explicit empty config prevents inheriting the repository's live Hosting
        # rewrite. Shared-project mode never deploys or creates Hosting resources.
        firebase = {"hosting": []}
    plan = {"shared_project": shared_project, "hosting_enabled": not shared_project,
            "cloud_run_invocation": "private IAM via developer proxy" if shared_project else "explicitly review Hosting invocation access",
            "production_writes_permitted": False,
            "status": "prepared_only_not_provisioned", "project": project, "bucket": bucket,
            "service": service, "region": "us-central1", "min_instances": 0, "max_instances": 1,
            "memory": "4Gi", "cpu": 1, "concurrency": 4, "timeout_seconds": 300,
            "runtime_service_account": f"mfi-runtime-staging@{project}.iam.gserviceaccount.com",
            "admin_secret_reference": "mfi-staging-admin-password:latest",
            "auth": "fresh custom app users/sessions; no Firebase Authentication migration",
            "blocking_prerequisites": ["Approved shared-project staging scope" if shared_project else "Dedicated staging project and linked billing", "Private staging bucket and dedicated IAM",
                                       "Fresh staging-only admin secret", "Sanitized source-only image and local public-data fixture",
                                       "Explicit approval for provisioning and billable build/deployment"]}
    output.mkdir(parents=True)
    (output / "firebase.json").write_text(json.dumps(firebase, indent=2), encoding="utf-8")
    (output / ".firebaserc").write_text(json.dumps({"projects": {"default": project}}, indent=2), encoding="utf-8")
    (output / "cloud-run.env.yaml").write_text("\n".join(f"{key}: {json.dumps(value)}" for key, value in env.items()) + "\n", encoding="utf-8")
    (output / "deployment-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shared-project", action="store_true", help="Explicitly prepare isolated staging resources inside medicaid-inspector; Hosting disabled")
    parser.add_argument("--service", default="mfi-api-staging")
    args = parser.parse_args()
    plan = prepare(args.project, args.bucket, args.output, shared_project=args.shared_project, service=args.service)
    print(json.dumps({"status": plan["status"], "files_written": 4}))


if __name__ == "__main__":
    main()
