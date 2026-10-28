import json
import pytest
from scripts import verify_production_privacy as guard


def resources():
    return {"approved_production_privacy_readonly": True,
            "services": [{"name": name, "url": "https://" + name + "-fixture.region.run.app"} for name in guard.SERVICES],
            "public_source_bucket": "fixture-public-source",
            "public_source_url": "https://storage.googleapis.com/fixture-public-source/medicaid-provider-spending.parquet"}


def test_exact_services_and_dataset_only_source_are_required():
    assert guard.validate(resources())
    config = resources(); config["services"][0]["name"] = "unapproved-service"
    with pytest.raises(ValueError): guard.validate(config)
    config = resources(); config["public_source_bucket"] = guard.PRIVATE_BUCKET
    with pytest.raises(ValueError): guard.validate(config)
    config = resources(); config["public_source_url"] += "?token=forbidden"
    with pytest.raises(ValueError): guard.validate(config)


def test_private_objects_receive_head_only_no_body_or_auth():
    calls = []
    def fake(url, **kwargs):
        calls.append((url, kwargs))
        if "/medicaid-inspector-data/" in url:
            assert kwargs == {"method": "HEAD", "limit": 0}
            return 403, {}, b""
        if url.endswith("/health") or url.endswith("/ready"): return 200, {}, b'{"status":"healthy","version":"fixture"}'
        if "/api/admin/" in url: return 401, {}, b""
        if kwargs["method"] == "HEAD": return 200, {"Content-Length": "100"}, b""
        assert kwargs["range_header"] == "bytes=0-3"
        return 206, {}, b"PAR1"
    result = guard.inspect_http(resources(), fake)
    assert result["http_checks_passed"] is True
    assert all(item["contents_read"] is False for item in result["private_objects"])
    assert len([url for url, _ in calls if "/medicaid-inspector-data/" in url]) == 2
    assert all("login" not in url for url, _ in calls)


def test_default_plan_sends_no_requests(tmp_path, monkeypatch, capsys):
    path = tmp_path / "resources.json"; path.write_text(json.dumps(resources()))
    monkeypatch.setattr(guard, "inspect_http", lambda *args: pytest.fail("No request permitted in plan"))
    assert guard.main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["no_requests_sent"] is True


def test_private_head_requires_403_not_missing_object_and_can_target_one_service():
    called = []
    def fake(url, **kwargs):
        called.append(url)
        if "/medicaid-inspector-data/" in url: return 404, {}, b""
        if url.endswith("/health") or url.endswith("/ready"): return 200, {}, b'{}'
        if "/api/admin/" in url: return 401, {}, b""
        return (200, {}, b"") if kwargs["method"] == "HEAD" else (206, {}, b"PAR1")
    result = guard.inspect_http(resources(), fake, selected_service="medicaid-inspector-api")
    assert len(result["services"]) == 1
    assert result["services"][0]["name"] == "medicaid-inspector-api"
    assert result["http_checks_passed"] is False
    assert all(item["denied"] is False for item in result["private_objects"])
