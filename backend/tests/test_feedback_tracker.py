"""
Regression tests for services/feedback_tracker.py — the undo-uses-stale-signals
bug and the synthetic-NPI exclusion (audit 2026-10-24).

These call feedback_tracker's module functions directly rather than going
through the HTTP API, and monkeypatch its module-level state dicts so this
test can't leak into (or be polluted by) any other test's use of the same
global state, or touch the real feedback_data.json (conftest.py already
redirects _FEEDBACK_FILE for every test via its state-module discovery).
"""
import services.feedback_tracker as ft


def _isolate(monkeypatch):
    """Give this test its own empty copies of every piece of module state."""
    monkeypatch.setattr(ft, "_signal_fp_counts", {})
    monkeypatch.setattr(ft, "_signal_tp_counts", {})
    monkeypatch.setattr(ft, "_dismissals", [])
    monkeypatch.setattr(ft, "_weight_adjustments", {})
    monkeypatch.setattr(ft, "_counted", {})
    monkeypatch.setattr(ft, "_npi_signal_snapshot", {})
    monkeypatch.setattr(ft, "_events", [])
    # No disk I/O from this test.
    monkeypatch.setattr(ft, "_save", lambda: None)


def _fake_signals(signals_by_npi: dict[str, list[str]]):
    def _active_signals(npi: str) -> list[str]:
        return list(signals_by_npi.get(npi, []))
    return _active_signals


def test_excluded_synthetic_npi_is_never_recorded(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(ft, "_active_signals", _fake_signals(
        {"1234567890": ["billing_concentration"]}))

    result = ft.record_confirmation("1234567890")

    assert result["recorded"] is False
    assert ft._signal_tp_counts == {}
    assert "1234567890" not in ft._counted


def test_relabel_undoes_using_original_snapshot_not_current_signals(monkeypatch):
    """The bug: provider NPI-X was dismissed (FP) while signal A was firing.
    Before a correction is made, a rescore changes which signals fire for
    NPI-X to signal B. If the correction (now confirmed as TP) undoes against
    TODAY's signals (B), signal A's false-positive count never gets
    decremented (a permanent leak) and signal B gets wrongly decremented even
    though it was never credited to this NPI. The fix must undo against the
    snapshot taken at the time of the ORIGINAL label (A), not today's (B)."""
    _isolate(monkeypatch)
    npi = "9999999999"
    signals_now = {npi: ["signal_a"]}
    monkeypatch.setattr(ft, "_active_signals", _fake_signals(signals_now))

    ft.record_dismissal(npi)  # signal_a counted as FP
    assert ft._signal_fp_counts == {"signal_a": 1}
    assert ft._npi_signal_snapshot[npi] == ["signal_a"]

    # Simulate a rescore: the provider's live signals have changed.
    signals_now[npi] = ["signal_b"]

    ft.record_confirmation(npi)  # now labeled TP

    # signal_a's FP contribution must be backed out (it was the ORIGINAL
    # signal credited to this NPI) ...
    assert ft._signal_fp_counts.get("signal_a", 0) == 0
    # ... and signal_b (today's signal, not part of the original label)
    # must NOT have been touched by the undo.
    assert "signal_b" not in ft._signal_fp_counts
    # The new TP label is recorded against today's signal.
    assert ft._signal_tp_counts == {"signal_b": 1}


def test_rebuild_counts_from_events_matches_live_counters(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(ft, "_active_signals", _fake_signals({
        "1111111111": ["sig_x"],
        "2222222222": ["sig_x", "sig_y"],
    }))

    ft.record_confirmation("1111111111")
    ft.record_dismissal("2222222222")

    rebuilt = ft.rebuild_counts_from_events()

    assert rebuilt["rebuilt_tp_counts"] == ft._signal_tp_counts
    assert rebuilt["rebuilt_fp_counts"] == ft._signal_fp_counts
    assert set(rebuilt["events_covered_npis"]) == {"1111111111", "2222222222"}


def test_excluded_npi_dropped_from_rebuild_even_if_present_in_legacy_counted(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(ft, "_counted", {"1234567890": "tp"})  # legacy contamination
    rebuilt = ft.rebuild_counts_from_events()
    assert rebuilt["rebuilt_tp_counts"] == {}
    assert "1234567890" not in rebuilt["events_covered_npis"]
