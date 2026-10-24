"""
Read-only audit: shows exactly what changes if the synthetic test NPI
"1234567890" (conftest's SAMPLE_PROVIDERS "Test Provider A") is removed from
feedback_data.json, WITHOUT writing anything.

Background: before 2026-10-24, tests never redirected
services.feedback_tracker's state file, so a test run against the real
backend wrote this NPI's dismissal/confirmation into the real
backend/feedback_data.json. feedback_tracker.py now excludes this NPI from
all future computation (see _EXCLUDED_NPIS), but per the project's own rule
("never delete real-world records without review"), the existing on-disk
entry is left alone until a human decides.

Run with:  python scripts/audit_feedback_contamination.py
"""
import json
import pathlib

_FEEDBACK_FILE = pathlib.Path(__file__).parent.parent / "feedback_data.json"
_CONTAMINATED_NPI = "1234567890"
# The exact signals conftest.py's SAMPLE_PROVIDERS assigns to this NPI.
_CONTAMINATED_SIGNALS = ["revenue_per_bene_outlier", "billing_concentration"]


def main() -> None:
    data = json.loads(_FEEDBACK_FILE.read_text(encoding="utf-8"))
    counted = data.get("counted", {})
    direction = counted.get(_CONTAMINATED_NPI)

    print(f"Feedback file: {_FEEDBACK_FILE}")
    print(f"NPI {_CONTAMINATED_NPI} present in 'counted': {direction!r}")
    if direction is None:
        print("Nothing to report — this NPI is not in the live file.")
        return

    counts_key = "tp_counts" if direction == "tp" else "fp_counts"
    counts = dict(data.get(counts_key, {}))
    print(f"\nCurrent {counts_key}:")
    for sig in _CONTAMINATED_SIGNALS:
        print(f"  {sig}: {counts.get(sig, 0)}")

    print(f"\nIf NPI {_CONTAMINATED_NPI}'s contribution is removed, {counts_key} would become:")
    corrected = dict(counts)
    for sig in _CONTAMINATED_SIGNALS:
        if corrected.get(sig):
            corrected[sig] = max(0, corrected[sig] - 1)
    for sig in _CONTAMINATED_SIGNALS:
        print(f"  {sig}: {corrected.get(sig, 0)}  (was {counts.get(sig, 0)})")

    print(
        "\nThis script changed nothing. To apply this correction, a human should "
        "edit feedback_data.json directly (drop the NPI from 'counted' and 'dismissals', "
        "and adjust the counts above), then let the app recompute weight_adjustments "
        "on the next normal disposition."
    )


if __name__ == "__main__":
    main()
