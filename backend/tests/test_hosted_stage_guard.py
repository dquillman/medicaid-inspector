import json
import pytest
from scripts import verify_hosted_stage as harness


def resources():
    return {"approved_staging_only": True, "project_id": "fixture-project", "service_name": "mfi-staging-fixture", "bucket": "mfi-staging-fixture-bucket", "service_url": "https://mfi-staging-fixture-123.region.run.app"}


def test_resource_guard_rejects_production_mismatched_host_and_redirect_targets():
    assert harness.validate_resources(resources())["approved_staging_only"] is True
    for field, value in [("bucket", "medicaid-inspector-data"), ("service_name", "mfi-production"), ("service_url", "https://production.run.app"), ("service_url", "https://mfi-staging-fixture-123.region.run.app@evil.test"), ("service_url", "http://mfi-staging-fixture-123.region.run.app"), ("approved_staging_only", False)]:
        config = resources(); config[field] = value
        with pytest.raises(ValueError): harness.validate_resources(config)


def test_plan_default_never_contacts_any_resource(tmp_path, monkeypatch, capsys):
    path = tmp_path / "resources.json"; path.write_text(json.dumps(resources()))
    monkeypatch.setattr(harness, "api", lambda *args, **kwargs: pytest.fail("Unexpected network request"))
    assert harness.main([str(path), "--mode", "cas"]) == 0
    assert json.loads(capsys.readouterr().out)["no_requests_sent"] is True


class PreconditionFailed(Exception): code = 412
class Blob:
    generation = None
    payload = None
    deleted = False
    def upload_from_string(self, payload, *, if_generation_match):
        if if_generation_match != (self.generation or 0): raise PreconditionFailed()
        self.payload = payload; self.generation = (self.generation or 0) + 1
    def download_as_bytes(self, *, if_generation_match):
        if if_generation_match != self.generation: raise PreconditionFailed()
        return self.payload
    def reload(self): pass
    def delete(self, *, if_generation_match):
        if if_generation_match != self.generation: raise PreconditionFailed()
        self.deleted = True
class Bucket:
    def __init__(self): self.object = Blob(); self.names = []
    def blob(self, name): self.names.append(name); return self.object


def test_cas_conflict_recovery_and_cleanup_use_only_exact_disposable_object():
    bucket = Bucket()
    result = harness.check_cas(bucket, "a" * 32)
    assert result["stale_write_rejected"] is True
    assert result["recovery_verified"] is True
    harness.cleanup_cas(bucket, result)
    assert bucket.object.deleted
    assert set(bucket.names) == {"verification/" + "a" * 32 + "/cas.json"}
    result["object_name"] = "outside-prefix"
    with pytest.raises(ValueError): harness.cleanup_cas(bucket, result)


def test_restart_verification_requires_fresh_revision_metadata(monkeypatch):
    receipt = {"service_url": resources()["service_url"], "marker_name": "staging-verification-fixture", "marker_id": "fixture-id", "evidence": {"case_id": "staging-verification-fixture", "evidence_id": "fixture-evidence", "sha256": __import__("hashlib").sha256(b"fixture-bytes").hexdigest()}}
    with pytest.raises(ValueError, match="fresh-instance"):
        harness.http_verify(resources(), receipt, {"before_revision": "same", "after_revision": "same", "fresh_instance_confirmed": True})
    monkeypatch.setattr(harness, "login", lambda config: "synthetic-token")
    def fake_api(config, path, **kwargs):
        if path.endswith("/verify"): return 200, {}, {"valid": True, "current_hash": receipt["evidence"]["sha256"]}
        if path.endswith("/download"): return 200, {}, b"fixture-bytes"
        return 200, {}, {"searches": [{"id": "fixture-id", "name": "staging-verification-fixture"}]}
    monkeypatch.setattr(harness, "api", fake_api)
    assert harness.http_verify(resources(), receipt, {"before_revision": "old", "after_revision": "new", "fresh_instance_confirmed": True})["persistence_after_restart_verified"]


def test_proxy_guard_allows_only_explicit_loopback():
    config = resources(); config["proxy_url"] = "http://127.0.0.1:8080"
    assert harness.validate_resources(config)["proxy_url"].endswith(":8080")
    for value in ("http://localhost:8080", "https://evil.test", "http://127.0.0.1:8080/other", "http://user:password@127.0.0.1:8080"):
        config["proxy_url"] = value
        with pytest.raises(ValueError): harness.validate_resources(config)
