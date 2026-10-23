"""Fraud Brain board cache: never make a page wait ~17s for a recompute that a
stale board can cover, and never run two recomputes at once."""
import threading
import time

import pytest

from services import fraud_brain as fb


def _join_refresh_threads():
    for t in threading.enumerate():
        if t.name == "fraud-brain-refresh":
            t.join(timeout=30)


@pytest.fixture
def brain(monkeypatch):
    # The app warms the board at startup; let that finish before faking compute.
    _join_refresh_threads()
    calls = {"n": 0}

    def fake_compute(limit=10):
        calls["n"] += 1
        time.sleep(0.3)
        return {"top": [{"npi": f"10000000{i:02d}"} for i in range(limit)], "computed": calls["n"]}

    monkeypatch.setattr(fb, "compute_top_frauds", fake_compute)
    monkeypatch.setattr(fb, "_oig_ready", lambda: True)
    monkeypatch.setattr(fb, "_apply_live_ledger", lambda rows: list(rows))
    fb.invalidate_cache()
    yield calls
    for t in threading.enumerate():
        if t.name == "fraud-brain-refresh":
            t.join(timeout=5)
    fb.invalidate_cache()


def test_stale_board_is_served_at_once_and_refreshed_in_background(brain):
    fb._cache["result"] = {"top": [{"npi": "1999999999"}], "computed": 0}
    fb._cache["computed_at"] = time.time() - fb.CACHE_TTL_SEC - 1

    t0 = time.time()
    out = fb._get_top_frauds(10, False)
    assert time.time() - t0 < 0.2, "a stale board must not block on a recompute"
    assert out["stale"] is True and out["top"][0]["npi"] == "1999999999"

    for t in threading.enumerate():
        if t.name == "fraud-brain-refresh":
            t.join(timeout=5)
    assert brain["n"] == 1
    assert fb._cache["result"]["computed"] == 1
    assert len(fb._cache["result"]["top"]) == fb._COMPUTE_DEPTH


def test_concurrent_cold_requests_share_one_compute(brain):
    results = []
    threads = [threading.Thread(target=lambda: results.append(fb._get_top_frauds(25, False)))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert brain["n"] == 1, "three cold callers must not each score every provider"
    assert all(len(r["top"]) == 25 for r in results)


def test_different_limits_do_not_evict_each_other(brain):
    fb._get_top_frauds(25, False)
    fb._get_top_frauds(500, False)
    fb._get_top_frauds(25, False)
    assert brain["n"] == 1


def test_warm_cache_fills_an_empty_board_once(brain):
    fb.warm_cache()
    fb.warm_cache()  # a second call while warming must not start another compute
    _join_refresh_threads()
    assert brain["n"] == 1
    assert fb._cache["result"] is not None
    fb.warm_cache()  # board present: nothing to do
    _join_refresh_threads()
    assert brain["n"] == 1


def test_blocking_warm_cache_computes_before_returning(brain):
    fb.warm_cache(blocking=True)
    assert brain["n"] == 1
    assert fb._cache["result"] is not None


def test_recompute_button_still_forces_a_fresh_board(brain):
    fb._get_top_frauds(10, False)
    fb._get_top_frauds(10, True)
    assert brain["n"] == 2
