"""Explicitly guarded hosted-staging verification. Default prints plan only.

Never call this against production. Credentials come from environment and are
never written to receipts. Operator must approve exact staging resources first.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

PRODUCTION_BUCKETS = {"medicaid-inspector-data"}


def validate_resources(config):
    if config.get("approved_staging_only") is not True:
        raise ValueError("Explicit staging approval marker required")
    service, bucket = config.get("service_name", ""), config.get("bucket", "")
    stage_word = re.compile(r"(?:^|-)(?:stage|staging)(?:-|$)")
    if not stage_word.search(service) or not stage_word.search(bucket):
        raise ValueError("Service and bucket names must explicitly identify staging")
    if not re.fullmatch(r"[a-z0-9-]{3,63}", service) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,62}", bucket) or bucket in PRODUCTION_BUCKETS:
        raise ValueError("Invalid or prohibited resource name")
    url = urlsplit(config.get("service_url", ""))
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".run.app")
            or not (url.hostname.startswith(service + "-") or url.hostname.startswith(service + "."))
            or url.port is not None or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("URL must identify the exact staging Cloud Run service")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", config.get("project_id", "")):
        raise ValueError("Explicit project identifier required")
    proxy = config.get("proxy_url")
    if proxy:
        parsed = urlsplit(proxy)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("Proxy must be an explicitly approved loopback port")
    return {**config, "service_url": config["service_url"].rstrip("/")}


def write_receipt(path, result):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Receipts are versioned; never silently replace prior evidence.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def check_cas(bucket, run_id):
    """Exactly one disposable object; no bucket listing or production reads."""
    if not re.fullmatch(r"[a-f0-9]{32}", run_id): raise ValueError("Invalid verification run identifier")
    name = "verification/" + run_id + "/cas.json"
    blob = bucket.blob(name)
    blob.upload_from_string(b'{"fixture":"v1"}', if_generation_match=0)
    first = int(blob.generation)
    blob.upload_from_string(b'{"fixture":"v2"}', if_generation_match=first)
    second = int(blob.generation)
    refused = False
    try:
        blob.upload_from_string(b'{"fixture":"stale"}', if_generation_match=first)
    except Exception as error:
        code = getattr(error, "code", None)
        code = code() if callable(code) else code
        if code == 412 or type(error).__name__ == "PreconditionFailed": refused = True
        else: raise
    if not refused: raise RuntimeError("Stale-generation overwrite was not rejected")
    if blob.download_as_bytes(if_generation_match=second) != b'{"fixture":"v2"}':
        raise RuntimeError("Conflict changed the newer remote object")
    # Recovery is explicit fresh generation/content inspection, never blind retry.
    blob.reload()
    if int(blob.generation) != second: raise RuntimeError("Unexpected concurrent writer")
    blob.upload_from_string(b'{"fixture":"reconciled"}', if_generation_match=second)
    final = int(blob.generation)
    payload = blob.download_as_bytes(if_generation_match=final)
    if payload != b'{"fixture":"reconciled"}': raise RuntimeError("Reconciled object content differs")
    return {"run_id": run_id, "object_name": name, "generation": final, "stale_write_rejected": True,
            "recovery_verified": True, "sha256": hashlib.sha256(payload).hexdigest()}


def cleanup_cas(bucket, receipt):
    run = receipt["run_id"]
    expected = "verification/" + run + "/cas.json"
    if not re.fullmatch(r"[a-f0-9]{32}", run) or receipt["object_name"] != expected:
        raise ValueError("Cleanup restricted to exact receipt-owned object")
    blob = bucket.blob(expected)
    payload = blob.download_as_bytes(if_generation_match=int(receipt["generation"]))
    if hashlib.sha256(payload).hexdigest() != receipt["sha256"]: raise ValueError("Cleanup object changed; preserve for reconciliation")
    blob.delete(if_generation_match=int(receipt["generation"]))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def api(config, path, *, token=None, body=None, method="GET", raw=False, content_type="application/json"):
    if not path.startswith("/api/") or ".." in path: raise ValueError("Only fixed API paths permitted")
    headers = {"Content-Type": content_type}
    if token: headers["Authorization"] = "Bearer " + token
    iam = os.environ.get("MFI_STAGING_IAM_TOKEN")
    if iam: headers["X-Serverless-Authorization"] = "Bearer " + iam
    request = Request(config.get("proxy_url", config["service_url"]).rstrip("/") + path, data=body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with build_opener(NoRedirect).open(request, timeout=45) as response:
            payload = response.read()
            return response.status, dict(response.headers), payload if raw else json.loads(payload or b"{}")
    except HTTPError as error:
        return error.code, dict(error.headers), {}  # Never print response/provider data.


def login(config):
    credential_path = os.environ.get("MFI_STAGING_CREDENTIALS_FILE")
    credentials = json.loads(pathlib.Path(credential_path).read_text()) if credential_path else {"username": os.environ["MFI_STAGING_USERNAME"], "password": os.environ["MFI_STAGING_PASSWORD"]}
    status, _, result = api(config, "/api/auth/login", method="POST", body={"username": credentials["username"], "password": credentials["password"]})
    if status not in (200, 202) or not result.get("token"): raise RuntimeError("Synthetic staging login failed")
    return result["token"]


def http_prepare(config):
    status, _, _ = api(config, "/api/saved-searches")
    if status not in (401, 403): raise RuntimeError("Unauthenticated protected route was not denied")
    token = login(config)
    status, _, _ = api(config, "/api/auth/me", token=token)
    if status != 200: raise RuntimeError("Authenticated protected route failed")
    marker = "staging-verification-" + uuid.uuid4().hex
    status, headers, result = api(config, "/api/saved-searches", token=token, method="POST", body={"name": marker, "filters": {"synthetic": True}})
    persistence = next((value for key, value in headers.items() if key.lower() == "x-mfi-persistence"), None)
    if status not in (200, 201, 202) or persistence not in ("durable", "pending"):
        raise RuntimeError("Synthetic write lacks persistence acknowledgment")
    case_id = marker
    payload = b"MFI hosted staging synthetic custody fixture; no provider data."
    boundary = "mfi" + uuid.uuid4().hex
    multipart = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="synthetic-custody.txt"\r\nContent-Type: text/plain\r\n\r\n').encode() + payload + ("\r\n--" + boundary + "--\r\n").encode()
    evidence_status, evidence_headers, evidence = api(config, "/api/cases/" + case_id + "/evidence", token=token, body=multipart, method="POST", content_type="multipart/form-data; boundary=" + boundary)
    evidence_ack = next((value for key, value in evidence_headers.items() if key.lower() == "x-mfi-persistence"), None)
    if evidence_status not in (200, 201, 202) or evidence_ack not in ("durable", "pending") or evidence.get("sha256_hash") != hashlib.sha256(payload).hexdigest():
        raise RuntimeError("Synthetic evidence upload lacked valid custody/durability acknowledgment")
    return {"service_url": config["service_url"], "evidence": {"case_id": case_id, "evidence_id": evidence["evidence_id"], "stored_filename": evidence["stored_filename"], "sha256": hashlib.sha256(payload).hexdigest(), "persistence": evidence_ack}, "marker_name": marker, "marker_id": result["search"]["id"], "persistence": persistence,
            "protected_route_denied": True, "authenticated_route_verified": True}


def http_verify(config, receipt, restart):
    if receipt["service_url"] != config["service_url"] or not receipt["marker_name"].startswith("staging-verification-"):
        raise ValueError("Marker receipt does not match staging resource")
    if (not restart.get("fresh_instance_confirmed") or not restart.get("before_revision") or not restart.get("after_revision")
            or restart["before_revision"] == restart["after_revision"]):
        raise ValueError("Explicit fresh-instance/new-revision metadata evidence required")
    token = login(config)
    status, _, result = api(config, "/api/saved-searches", token=token)
    matches = [row for row in result.get("searches", []) if row.get("id") == receipt["marker_id"] and row.get("name") == receipt["marker_name"]]
    if status != 200 or len(matches) != 1: raise RuntimeError("Acknowledged synthetic write did not survive fresh instance")
    evidence = receipt.get("evidence")
    if not evidence or evidence.get("case_id") != receipt["marker_name"]:
        raise ValueError("Synthetic custody evidence receipt required")
    base = "/api/cases/" + evidence["case_id"] + "/evidence/" + evidence["evidence_id"]
    status, _, verified = api(config, base + "/verify", token=token)
    if status != 200 or verified.get("valid") is not True or verified.get("current_hash") != evidence["sha256"]:
        raise RuntimeError("Evidence integrity did not survive fresh instance")
    status, _, content = api(config, base + "/download", token=token, raw=True)
    if status not in (200, 202) or hashlib.sha256(content).hexdigest() != evidence["sha256"]:
        raise RuntimeError("Cold evidence bytes do not match custody receipt")
    return {"evidence_after_restart_verified": True, "persistence_after_restart_verified": True, "before_revision": restart["before_revision"], "after_revision": restart["after_revision"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=pathlib.Path)
    parser.add_argument("--mode", choices=["plan", "cas", "cas-cleanup", "http-prepare", "http-verify"], default="plan")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--receipt", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--restart-evidence", type=pathlib.Path)
    args = parser.parse_args(argv)
    config = validate_resources(json.loads(args.resources.read_text()))
    if args.mode == "plan" or not args.execute:
        print(json.dumps({"status": "plan_only", "no_requests_sent": True, "service": config["service_name"], "bucket": config["bucket"], "mode": args.mode}))
        return 0
    if args.output is None: parser.error("Versioned output receipt required before execution")
    if args.output.exists(): parser.error("Output receipt already exists")
    if args.mode in ("cas-cleanup", "http-verify") and args.receipt is None: parser.error("Prior exact-resource receipt required")
    if args.mode == "http-verify" and args.restart_evidence is None: parser.error("Restart metadata evidence required")
    if args.mode.startswith("http") and not os.environ.get("MFI_STAGING_CREDENTIALS_FILE") and not all(os.environ.get(key) for key in ("MFI_STAGING_USERNAME", "MFI_STAGING_PASSWORD")):
        parser.error("Synthetic staging credentials must be set in environment")
    intent = {"mode": args.mode, "service": config["service_name"], "bucket": config["bucket"], "production_access_permitted": False}
    if args.mode == "cas": intent["run_id"] = uuid.uuid4().hex
    write_receipt(args.output.with_suffix(args.output.suffix + ".intent.json"), intent)
    if args.mode.startswith("cas"):
        from google.cloud import storage
        token = os.environ.get("MFI_STAGING_GCS_TOKEN")
        if token:
            from google.oauth2.credentials import Credentials
            client = storage.Client(project=config["project_id"], credentials=Credentials(token=token))
        else:
            client = storage.Client(project=config["project_id"])
        bucket = client.bucket(config["bucket"])
        if args.mode == "cas":
            result = {"bucket": config["bucket"], **check_cas(bucket, intent["run_id"])}
        else:
            receipt = json.loads(args.receipt.read_text())
            if receipt["bucket"] != config["bucket"]: raise ValueError("Cleanup receipt bucket mismatch")
            cleanup_cas(bucket, receipt)
            result = {"cleanup_verified": True, "run_id": receipt["run_id"]}
    elif args.mode == "http-prepare": result = http_prepare(config)
    else: result = http_verify(config, json.loads(args.receipt.read_text()), json.loads(args.restart_evidence.read_text()))
    write_receipt(args.output, result)
    print(json.dumps({"status": "completed", "mode": args.mode, "receipt_written": True}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
