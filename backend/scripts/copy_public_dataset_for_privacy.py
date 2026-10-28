"""Approved one-object server-side copy; never changes production IAM/services.

Run on the coordinating host only with MFI_APPROVED_PUBLIC_DATA_COPY=1.
Cloud SDK token is captured in memory, never printed, saved or passed in args.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

PROJECT = "medicaid-inspector"
PROJECT_NUMBER = "447172598773"
SOURCE_BUCKET = "medicaid-inspector-data"
DESTINATION_BUCKET = "medicaid-inspector-public-aggregates"
OBJECT = "medicaid-provider-spending.parquet"
SOURCE_GENERATION = 1774579251010800
EXPECTED_SIZE = 2940234191
EXPECTED_CRC = "KFYNRQ=="
PUBLIC_URL = f"https://storage.googleapis.com/{DESTINATION_BUCKET}/{OBJECT}"


def main():
    if os.environ.get("MFI_APPROVED_PUBLIC_DATA_COPY") != "1":
        raise RuntimeError("Explicit approved-copy execution guard required")
    from google.cloud import storage
    from google.oauth2.credentials import Credentials
    from google.api_core.exceptions import NotFound
    cli = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not cli:
        raise RuntimeError("Cloud SDK unavailable")
    authentication = subprocess.run([cli, "auth", "print-access-token", "--quiet"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if authentication.returncode or not authentication.stdout.strip():
        raise RuntimeError("Cloud SDK authentication unavailable; credential output suppressed")
    credentials = Credentials(authentication.stdout.decode().strip())
    authentication.stdout = b""
    client = storage.Client(project=PROJECT, credentials=credentials)
    receipts = Path(__file__).resolve().parents[1] / "private_validations" / "20261027-privacy-repair"
    receipts.mkdir(parents=True, exist_ok=True)
    source_bucket = client.bucket(SOURCE_BUCKET)
    source = source_bucket.blob(OBJECT, generation=SOURCE_GENERATION)
    source.reload()
    if int(source.size) != EXPECTED_SIZE or source.crc32c != EXPECTED_CRC:
        raise RuntimeError("Pinned source checksum/size mismatch")
    source_metadata = {"bucket": SOURCE_BUCKET, "object": OBJECT, "generation": str(source.generation),
                       "size": source.size, "crc32c": source.crc32c, "md5": source.md5_hash}
    (receipts / "pinned-public-source.metadata.json").write_text(json.dumps(source_metadata, indent=2))
    created = False
    try:
        target = client.get_bucket(DESTINATION_BUCKET)
    except NotFound:
        target = client.bucket(DESTINATION_BUCKET)
        target.iam_configuration.uniform_bucket_level_access_enabled = True
        target.iam_configuration.public_access_prevention = "inherited"
        target = client.create_bucket(target, location="us-central1")
        created = True
    if str(target._properties.get("projectNumber")) != PROJECT_NUMBER:
        raise RuntimeError("Destination bucket ownership not verified")
    if not target.iam_configuration.uniform_bucket_level_access_enabled:
        raise RuntimeError("Destination uniform bucket access not enabled")
    if target.iam_configuration.public_access_prevention == "enforced":
        raise RuntimeError("Public access prevention enforced; no policy override attempted")
    destination = target.blob(OBJECT)
    try:
        destination.reload()
    except NotFound:
        # Server-side copy: exact source generation, create-only destination.
        destination = source_bucket.copy_blob(source, target, new_name=OBJECT,
            source_generation=SOURCE_GENERATION, if_source_generation_match=SOURCE_GENERATION,
            if_generation_match=0, timeout=300)
        destination.reload()
    if int(destination.size) != EXPECTED_SIZE or destination.crc32c != source.crc32c:
        raise RuntimeError("Destination checksum/size mismatch; no public grant applied")
    if source.md5_hash and destination.md5_hash != source.md5_hash:
        raise RuntimeError("Destination MD5 mismatch; no public grant applied")
    names = [blob.name for blob in client.list_blobs(DESTINATION_BUCKET, max_results=2)]
    if names != [OBJECT]:
        raise RuntimeError("Destination contains unexpected objects; public grant withheld")
    policy = target.get_iam_policy(requested_policy_version=3)
    binding = next((item for item in policy.bindings if item["role"] == "roles/storage.objectViewer"), None)
    if binding is None:
        policy.bindings.append({"role": "roles/storage.objectViewer", "members": {"allUsers"}})
    else:
        binding["members"].add("allUsers")
    target.set_iam_policy(policy)
    # Anonymous, bounded validation. Read only four public header bytes.
    request = urllib.request.Request(PUBLIC_URL, headers={"Range": "bytes=0-3"})
    with urllib.request.urlopen(request, timeout=30) as response:
        status, content_range, prefix = response.status, response.headers.get("Content-Range"), response.read(4)
    if status != 206 or content_range != f"bytes 0-3/{EXPECTED_SIZE}" or prefix != b"PAR1":
        raise RuntimeError("Anonymous public Parquet range check failed")
    receipt = {"status": "public_dataset_copy_verified", "verified_at": datetime.now(timezone.utc).isoformat(),
               "bucket": DESTINATION_BUCKET, "bucket_created": created, "object": OBJECT, "url": PUBLIC_URL,
               "source_generation": str(SOURCE_GENERATION), "destination_generation": str(destination.generation),
               "size": destination.size, "crc32c": destination.crc32c,
               "md5": destination.md5_hash, "md5_verified": bool(source.md5_hash), "sha256_verified": False,
               "copy_method": "GCS server-side copy with pinned source generation and destination generation-match zero",
               "anonymous_range_status": status, "bytes_read": 4, "parquet_header_valid": True,
               "production_service_changes": False, "production_state_bucket_iam_changes": False}
    (receipts / "public-dataset-copy.receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never echo remote request headers/credentials or arbitrary SDK errors.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        sys.exit(1)
