"""Read-only production privacy/source validation; plan-only without --execute.

No login, session creation, writes, retries, or private-object GET requests.
Only exact approved service names and public source path are accepted.
"""
import argparse
import json
import pathlib
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

SERVICES = {"medicaid-inspector-api", "medicaid-inspector"}
PRIVATE_BUCKET = "medicaid-inspector-data"
PRIVATE_OBJECTS = ("users.json", "app.db")


def validate(config):
    if config.get("approved_production_privacy_readonly") is not True:
        raise ValueError("Explicit read-only privacy validation approval required")
    services = config.get("services", [])
    if {item.get("name") for item in services} != SERVICES or len(services) != 2:
        raise ValueError("Only the two explicitly approved production services are permitted")
    for item in services:
        url = urlsplit(item.get("url", ""))
        if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".run.app")
                or not (url.hostname.startswith(item["name"] + "-") or url.hostname.startswith(item["name"] + "."))
                or url.port or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("Production service URL does not match allowlist")
    bucket = config.get("public_source_bucket", "")
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,62}", bucket) or bucket == PRIVATE_BUCKET:
        raise ValueError("Public source must use separately approved dataset-only bucket")
    expected = "https://storage.googleapis.com/" + bucket + "/medicaid-provider-spending.parquet"
    if config.get("public_source_url") != expected:
        raise ValueError("Only the exact approved public Parquet object may be read")
    return config


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def request(url, *, method="HEAD", range_header=None, limit=0):
    if method not in ("HEAD", "GET"): raise ValueError("Read-only HTTP methods required")
    headers = {"Range": range_header} if range_header else {}
    try:
        with build_opener(NoRedirect).open(Request(url, method=method, headers=headers), timeout=45) as response:
            return response.status, dict(response.headers), response.read(limit) if limit else b""
    except HTTPError as error:
        return error.code, {}, b""  # Do not read or expose error bodies.


def inspect_http(config, transport=request, *, selected_service=None):
    report = {"services": [], "private_objects": [], "no_login_or_mutation": True}
    for service in config["services"]:
        if selected_service is not None and service["name"] != selected_service: continue
        base = service["url"].rstrip("/")
        status, _, payload = transport(base + "/health", method="GET", limit=4096)
        health = {}
        if status == 200:
            try:
                decoded = json.loads(payload)
                health = {key: decoded.get(key) for key in ("status", "version")}
            except (ValueError, TypeError): pass
        ready_status, _, _ = transport(base + "/ready", method="GET", limit=4096)
        protected = {}
        for path in ("/api/admin/dataset-info", "/api/admin/data-quality"):
            code, _, _ = transport(base + path, method="GET", limit=0)
            protected[path] = {"status": code, "anonymous_denied": code in (401, 403)}
        report["services"].append({"name": service["name"], "health_status": status, "ready_status": ready_status, "health": health,
                                   "expected_revision": service.get("revision"), "protected_routes": protected,
                                   "authenticated_data_source_not_queried": True})
    for name in PRIVATE_OBJECTS:
        code, _, _ = transport("https://storage.googleapis.com/" + PRIVATE_BUCKET + "/" + name, method="HEAD", limit=0)
        report["private_objects"].append({"object": name, "anonymous_head_status": code, "denied": code == 403, "contents_read": False})
    url = config["public_source_url"]
    head, headers, _ = transport(url, method="HEAD", limit=0)
    code, _, magic = transport(url, method="GET", range_header="bytes=0-3", limit=4)
    metadata = {key.lower(): value for key, value in headers.items() if key.lower() in ("content-length", "etag", "x-goog-generation")}
    report["public_source"] = {"head_status": head, "range_status": code, "parquet_magic_valid": magic == b"PAR1", "range_respected": code == 206, "metadata": metadata}
    report["http_checks_passed"] = (all(item["denied"] for item in report["private_objects"])
        and head == 200 and code == 206 and magic == b"PAR1"
        and all(item["health_status"] == 200 and item["ready_status"] == 200 and all(route["anonymous_denied"] for route in item["protected_routes"].values()) for item in report["services"]))
    return report


def inspect_parquet(config, *, aggregate=False):
    import duckdb
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions=false")
        connection.execute("SET autoload_known_extensions=false")
        connection.execute("LOAD httpfs")
        source = config["public_source_url"]
        schema = connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [source]).fetchall()
        required = {"BILLING_PROVIDER_NPI_NUM", "CLAIM_FROM_MONTH", "TOTAL_PAID", "TOTAL_CLAIMS", "TOTAL_UNIQUE_BENEFICIARIES"}
        names = {str(row[0]).upper() for row in schema}
        metadata = connection.execute("SELECT num_rows,num_row_groups FROM parquet_file_metadata(?)", [source]).fetchone()
        result = {"schema_columns": [{"name": row[0], "type": row[1]} for row in schema],
                  "required_columns_present": required <= names, "metadata_rows": metadata[0], "row_groups": metadata[1],
                  "raw_aggregate_executed": aggregate}
        if aggregate:
            # Only whole-dataset aggregate counts/totals; no provider identifiers
            # or example records can enter the report.
            row = connection.execute('SELECT COUNT(*), SUM(TOTAL_PAID), SUM(TOTAL_CLAIMS) FROM (SELECT TOTAL_PAID,TOTAL_CLAIMS FROM read_parquet(?) LIMIT 1000)', [source]).fetchone()
            result["raw_aggregate"] = {"scope": "first1000rows_only_not_full_dataset", "rows": row[0], "total_paid": str(row[1]), "total_claims": str(row[2])}
            result["sample_count_matches_limit"] = row[0] == min(metadata[0], 1000)
        return result
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=pathlib.Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source-query", action="store_true")
    parser.add_argument("--service", choices=sorted(SERVICES), help="Validate one service during controlled cutover")
    parser.add_argument("--raw-aggregate", action="store_true", help="Explicitly permit aggregate query over at most1000 public-source rows; row-group transfer may exceed those rows")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        config = validate(json.loads(args.resources.read_text()))
        if not args.execute:
            print(json.dumps({"status": "plan_only", "no_requests_sent": True, "private_requests": "HEAD only", "production_mutations": False}))
            return 0
        if args.output is None or args.output.exists(): parser.error("New versioned report output required")
        report = inspect_http(config, selected_service=args.service)
        passed = report["http_checks_passed"]
        if args.source_query or args.raw_aggregate:
            try:
                report["parquet"] = inspect_parquet(config, aggregate=args.raw_aggregate)
                source_passed = bool(report["parquet"]["required_columns_present"] and report["parquet"]["metadata_rows"] > 0
                                     and (not args.raw_aggregate or report["parquet"].get("sample_count_matches_limit")))
            except Exception:
                report["parquet"] = {"status": "unavailable", "details_suppressed": True}
                source_passed = False
            passed = passed and source_passed
        report["requested_checks_passed"] = passed
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, default=str)
        print(json.dumps({"report_written": True, "http_checks_passed": report["http_checks_passed"], "no_private_contents_read": True}))
        return 0 if report["requested_checks_passed"] else 1
    except Exception:
        print(json.dumps({"status": "validation_failed", "details_suppressed": True, "no_mutations_performed": True}))
        return 1


if __name__ == "__main__": raise SystemExit(main())
