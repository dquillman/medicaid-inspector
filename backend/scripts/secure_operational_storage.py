"""Approved operational-bucket privacy repair after verified source cutovers.

Never reads object contents, changes app data, or changes project-wide IAM.
"""
import json
import os
from pathlib import Path
import subprocess

PROJECT = "medicaid-inspector"
PRIVATE = "medicaid-inspector-data"
PUBLIC = "medicaid-inspector-public-aggregates"
URL = f"https://storage.googleapis.com/{PUBLIC}/medicaid-provider-spending.parquet"
CLI = r"G:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"


def remove_public_viewer(bindings):
    result = []
    for binding in bindings:
        public = set(binding["members"]) & {"allUsers", "allAuthenticatedUsers"}
        if public and (binding["role"] != "roles/storage.objectViewer" or public != {"allUsers"}):
            raise ValueError("Unexpected public grant requires explicit reconciliation")
        current = dict(binding)
        current["members"] = set(binding["members"]) - {"allUsers"}
        if current["members"]:
            result.append(current)
    return result


def main():
    if os.environ.get("MFI_APPROVED_OPERATIONAL_PRIVACY_REPAIR") != "1":
        raise ValueError("Explicit approved privacy repair required")
    from google.cloud import storage
    from google.oauth2.credentials import Credentials
    folder = Path(__file__).resolve().parents[1] / "private_validations" / "20261027-privacy-repair"
    if (folder / "operational-privacy.receipt.json").exists():
        raise ValueError("Completed receipt already exists; inspect before repeating")
    for service in ("medicaid-inspector-api", "medicaid-inspector"):
        expected = json.loads((folder / (service + ".cutover.json")).read_text())
        result = subprocess.run([CLI, "run", "services", "describe", service,
                                 "--project=" + PROJECT, "--region=us-central1", "--format=json"],
                                capture_output=True, check=True)
        live = json.loads(result.stdout)
        container = live["spec"]["template"]["spec"]["containers"][0]
        environment = {item["name"]: item.get("value") for item in container.get("env", [])}
        if (environment.get("PARQUET_URL") != URL or environment.get("GCS_BUCKET") == PUBLIC
                or container["image"] != expected["pinned_image"]
                or live["status"]["latestReadyRevisionName"] != expected["after_revision"]
                or not any(t.get("revisionName") == expected["after_revision"] and t.get("percent") == 100
                           for t in live["status"]["traffic"])):
            raise ValueError("Production cutover prerequisites drifted")
    token = subprocess.run([CLI, "auth", "print-access-token", "--quiet"], capture_output=True, check=True)
    client = storage.Client(project=PROJECT, credentials=Credentials(token.stdout.decode().strip()))
    token.stdout = b""
    public = client.get_bucket(PUBLIC)
    if [blob.name for blob in client.list_blobs(PUBLIC, max_results=2)] != ["medicaid-provider-spending.parquet"]:
        raise ValueError("Public bucket is not dataset-only")
    bucket = client.get_bucket(PRIVATE)
    policy = bucket.get_iam_policy(requested_policy_version=3)
    with (folder / "state-policy.immediately-before-revoke.json").open("x") as stream:
        json.dump(policy.to_api_repr(), stream, indent=2)
    policy.bindings = remove_public_viewer(policy.bindings)
    # Existing etag is retained: a concurrent IAM edit must not be overwritten.
    bucket.set_iam_policy(policy)
    bucket.reload()
    bucket.iam_configuration.public_access_prevention = "enforced"
    bucket.patch(if_metageneration_match=bucket.metageneration)
    bucket.reload()
    final = bucket.get_iam_policy(requested_policy_version=3)
    if any(set(b["members"]) & {"allUsers", "allAuthenticatedUsers"} for b in final.bindings):
        raise ValueError("Public IAM grant remains")
    if bucket.iam_configuration.public_access_prevention != "enforced":
        raise ValueError("Public access prevention not enforced")
    with (folder / "state-policy.after-revoke.json").open("x") as stream:
        json.dump(final.to_api_repr(), stream, indent=2)
    report = {"bucket": PRIVATE, "anonymous_iam_grants": 0, "public_access_prevention": "enforced",
              "uniform_bucket_access": bucket.iam_configuration.uniform_bucket_level_access_enabled,
              "project_iam_changed": False, "object_contents_read": False, "objects_modified": False,
              "services_cutover_verified": True, "public_bucket_remains_dataset_only": True}
    with (folder / "operational-privacy.receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
