"""Staging snapshot reader stays bounded to one provider row."""
import json
import pytest
from scripts.validate_refresh import iter_provider_rows, summarize_snapshot


def test_stream_provider_document_across_chunk_boundary(tmp_path):
    path = tmp_path / "snapshot.json"
    rows = [{"npi": "synthetic-a", "risk_score": 5, "padding": "x" * (1024*1024 + 100)},
            {"npi": "synthetic-b", "risk_score": 15, "flags": [{"signal": "demo", "flagged": True}]}]
    path.write_text(json.dumps({"saved_at": 1, "providers": rows}))
    assert list(iter_provider_rows(path)) == rows
    summary, scores = summarize_snapshot(path)
    assert summary["providers"] == 2
    assert summary["mean_score"] == 10
    assert summary["scores_over_10"] == 1
    assert summary["active_signals"] == {"demo": 1}
    assert len(scores) == 2


def test_stream_root_array_and_empty_array(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("[]")
    assert list(iter_provider_rows(path)) == []
    path.write_text('[{"npi":"synthetic","risk_score":1}]')
    assert summarize_snapshot(path)[0]["providers"] == 1


def test_stream_rejects_truncated_snapshot(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text('{"providers":[{"npi":')
    with pytest.raises(ValueError, match="Truncated"):
        list(iter_provider_rows(path))
