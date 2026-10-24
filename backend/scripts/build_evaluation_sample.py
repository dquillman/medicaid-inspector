"""
Build a frozen top-50 evaluation sample for measuring actual effectiveness
(audit 2026-10-24, item 12).

This does NOT compute or invent an accuracy/precision/ROI number — the review
explicitly warned against that ("Do not invent accuracy, recoveries,
customers, or ROI"). It only freezes the current top-50 Fraud Brain leads
plus the evidence snapshot behind each one, and leaves every judgment column
blank for Dave (or an independent reviewer) to fill in by hand.

Usage (run against a live backend process / imported modules, read-only):
    python scripts/build_evaluation_sample.py

Writes backend/evaluation_samples/top50_<YYYY-MM-DD>.csv with columns:
    npi, provider_name, risk_score, flag_count, evidence_summary,
    analyst_suspicion (blank — fill in: high/medium/low),
    independently_confirmed (blank — fill in: yes/no/unresolved, cite the
        source: OIG/MFCU response, DOJ action, press report, etc.),
    unresolved (blank — fill in: yes/no),
    reviewer, review_date, notes

Re-run periodically (e.g. monthly) to build a time series of frozen samples —
never overwrite a prior sample, since the acceptance criteria for item 12
requires tracking unresolved counts and uncertainty over time, not a single
snapshot.
"""
import csv
import datetime
import pathlib
import sys

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

OUT_DIR = _BACKEND_DIR / "evaluation_samples"


def main() -> int:
    from services.fraud_brain import get_top_frauds

    result = get_top_frauds(limit=50, force_refresh=False)
    top = result.get("top", [])
    if not top:
        print("No Fraud Brain leads available — run a scan first.")
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    out_path = OUT_DIR / f"top50_{today}.csv"
    if out_path.exists():
        print(f"{out_path} already exists — refusing to overwrite a frozen sample. "
              f"Delete it first if you really want to rebuild today's sample.")
        return 1

    fieldnames = [
        "npi", "provider_name", "risk_score", "flag_count", "evidence_summary",
        "analyst_suspicion", "independently_confirmed", "unresolved",
        "reviewer", "review_date", "notes",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in top:
            evidence = p.get("evidence") or []
            evidence_summary = "; ".join(
                f"{e.get('source', '?')}: {e.get('detail', '')}" for e in evidence
            )
            writer.writerow({
                "npi": p.get("npi", ""),
                "provider_name": p.get("provider_name", ""),
                "risk_score": p.get("risk_score", ""),
                "flag_count": len(p.get("flags") or []),
                "evidence_summary": evidence_summary,
                "analyst_suspicion": "",
                "independently_confirmed": "",
                "unresolved": "",
                "reviewer": "",
                "review_date": "",
                "notes": "",
            })

    print(f"Wrote {len(top)} rows to {out_path}")
    print(
        "Next step (manual, not automated): for each row, fill in "
        "analyst_suspicion (your read, before checking anything else), then "
        "independently_confirmed (only after checking an outside source — "
        "an OIG/MFCU response, a DOJ action, a news report — never leave "
        "'confirmed' based on this app's own score). Rows you can't resolve "
        "either way go in 'unresolved', not forced into yes/no — item 12's "
        "whole point is tracking that unresolved count honestly instead of "
        "hiding it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
