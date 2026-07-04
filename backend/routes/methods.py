"""
Public methodology endpoint — powers the /methods transparency page.

A solo public-data tipster lives on credibility: this publishes, with no auth,
exactly how the 18 signals work (label + plain-English explanation + the CFR/USC
citations behind each), the measured per-signal precision from analyst feedback
(true/false-positive counts → precision, the numbers feedback_tracker already
computes), an honest data-provenance statement, and how the composite score is
formed. Nothing here is PHI or provider-identifying.
"""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/methods", tags=["methods"])  # intentionally NO auth — public


# Honest provenance (corrected 2026-06-13): core spend is REAL Medicaid.
_PROVENANCE = {
    "core_dataset": "HHS “Medicaid Provider Spending by HCPCS” (T-MSIS-derived, released Feb 2026)",
    "is_real_medicaid": True,
    "coverage": "National, provider-level (NPI), Medicaid FFS + managed care + CHIP, 2018–2024.",
    "free_and_dua_free": True,
    "known_limits": [
        "Outpatient / professional claims only — no inpatient, prescription drugs, or long-term care.",
        "No diagnoses or HCPCS modifiers; claim/procedure rollups, not line-level records.",
        "Cells under 12 claims are suppressed; managed-care completeness varies by state.",
        "Rows missing a billing or servicing NPI are excluded (they carry inflated capitation).",
    ],
    "medicare_proxy_note": (
        "One signal — diagnosis_procedure_mismatch — uses the CMS Medicare MUP file as a "
        "diagnosis denominator (Medicaid claims carry no diagnoses). It is a supplementary "
        "proxy that only applies to providers with a Medicare panel and abstains (contributes "
        "nothing) otherwise. All other signals run on the real Medicaid data above."
    ),
    "enrichment_sources": ["NPPES (provider identity/taxonomy)", "OIG LEIE exclusions", "SAM.gov exclusions", "CMS Open Payments"],
}

_COMPOSITE_NOTE = (
    "Each signal returns a 0–100 sub-score and a weight; the composite risk score is the "
    "weighted sum, capped at 100. It is a RANKING of relative suspicion (worked top-down), "
    "NOT a calibrated probability — a score of 80 does not mean “80% likely fraud.” "
    "Signals that lack the data to fire abstain (contribute zero) rather than diluting the score."
)


@router.get("")
async def get_methods(request: Request) -> dict:
    """Per-signal methodology + provenance (public).

    The methodology itself — labels, plain-English explanations, and CFR/USC
    citations — is fully public for credibility. The measured per-signal
    precision / true-positive / false-positive counts are only included for
    authenticated callers: they hand an adversarial provider a roadmap of which
    signals are weakest and are operational data, not methodology.
    """
    from services.narrative_generator import _SIGNAL_META
    from services.feedback_tracker import get_feedback_summary
    from routes.auth import get_current_user

    authed = await get_current_user(request) is not None

    fb = get_feedback_summary()
    precision_by_signal = {s["signal"]: s for s in fb.get("signal_stats", [])}

    signals = []
    for sig, meta in _SIGNAL_META.items():
        entry = {
            "signal": sig,
            "label": meta.get("label", sig.replace("_", " ").title()),
            "explanation": meta.get("explanation", ""),
            "citations": meta.get("citations", []),
        }
        if authed:
            stats = precision_by_signal.get(sig) or {}
            # measured-precision block (None until enough analyst dispositions exist)
            entry["precision"] = stats.get("precision")
            entry["true_positives"] = stats.get("true_positives", 0)
            entry["false_positives"] = stats.get("false_positives", 0)
            entry["sample_size"] = stats.get("total", 0)
            entry["weight_adjustment"] = stats.get("weight_adjustment", 1.0)
        signals.append(entry)

    signals.sort(key=lambda s: s["label"])
    result = {
        "signal_count": len(signals),
        "signals": signals,
        "provenance": _PROVENANCE,
        "composite_methodology": _COMPOSITE_NOTE,
    }
    if authed:
        result["feedback_totals"] = {
            "dispositions": fb.get("total_dismissals", 0),
            "true_positive_signal_hits": fb.get("total_tp_signals", 0),
            "false_positive_signal_hits": fb.get("total_fp_signals", 0),
        }
    return result
