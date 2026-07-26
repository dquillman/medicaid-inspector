"""
Public methodology endpoint — powers the /methods transparency page.

A solo public-data tipster lives on credibility: this publishes, with no auth,
exactly how the active signals work (label + plain-English explanation + the
CFR/USC citations behind each), which signals have been RETIRED and why, what
this tool structurally cannot detect, the measured per-signal precision from
analyst feedback (true/false-positive counts → precision, the numbers
feedback_tracker already computes), an honest data-provenance statement, and how
the composite score is formed. Nothing here is PHI or provider-identifying.
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
        "None. Every active signal runs on the real Medicaid data above. The one signal that "
        "used a Medicare proxy (diagnosis_procedure_mismatch, which read chronic-condition "
        "prevalence from the CMS Medicare MUP file as a stand-in for the diagnoses Medicaid "
        "claims omit) was RETIRED on 2026-07-26: it fired on 2 of 106,660 scanned providers, "
        "and no MFI finding should rest on another payer's population."
    ),
    "all_data_public": True,
    "public_data_note": (
        "Every dataset behind this tool is public, free, and requires no data-use agreement. "
        "MFI holds no PHI and no beneficiary-level records — all analysis is provider-level "
        "aggregate. Any finding here can be re-derived by anyone from the same public files."
    ),
    "enrichment_sources": ["NPPES (provider identity/taxonomy)", "OIG LEIE exclusions", "SAM.gov exclusions", "CMS Open Payments"],
}

# What this tool structurally CANNOT see. Published for the same reason the
# signals are: a tipster's credibility depends on being explicit about the
# limits of the evidence, and a reviewer should not have to infer them.
_OUT_OF_SCOPE = {
    "note": (
        "These fraud types are not unimplemented — they are undetectable from public data. "
        "The public Medicaid file is pre-aggregated to billing NPI x HCPCS x month, so "
        "within-claim detail (line items, modifiers, service dates, ordering/referring NPI) "
        "does not exist in any dataset MFI can lawfully obtain. The only line-level source "
        "(T-MSIS/TAF via ResDAC) requires IRB approval, a HIPAA waiver and an institutional "
        "signatory. MFI detects provider-level patterns and claims nothing beyond that."
    ),
    "cannot_detect": [
        "Unbundling — billing component codes separately instead of the bundled code.",
        "Duplicate billing — the same service billed twice on one or more claims.",
        "Line-item upcoding — a single service billed at a higher-intensity code.",
        "Modifier abuse (e.g. -25, -59) — modifiers are not published in this dataset.",
        "Phantom referrals — no ordering or referring NPI is published.",
        "Anything requiring a diagnosis — Medicaid claims here carry no diagnosis codes.",
    ],
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
    retired = []
    for sig, meta in _SIGNAL_META.items():
        entry = {
            "signal": sig,
            "label": meta.get("label", sig.replace("_", " ").title()),
            "explanation": meta.get("explanation", ""),
            "citations": meta.get("citations", []),
        }
        # A retired OR PARKED signal keeps its entry (historical flags must still
        # explain themselves) but must never be counted as active — signal_count
        # is a public claim about what this tool currently does. Parked was
        # missed on the first pass, which published corporate_shell_risk as a
        # live scored signal while it contributed nothing.
        if meta.get("retired") or meta.get("parked"):
            if meta.get("retired"):
                entry["status"] = "retired"
                entry["retired"] = meta["retired"]
                entry["retired_reason"] = meta.get("retired_reason", "")
            else:
                entry["status"] = "parked"
                entry["parked"] = meta["parked"]
                entry["parked_reason"] = meta.get("parked_reason", "")
            retired.append(entry)
            continue
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
    retired.sort(key=lambda s: s["label"])
    result = {
        "signal_count": len(signals),
        "signals": signals,
        "retired_signals": retired,
        "provenance": _PROVENANCE,
        "out_of_scope": _OUT_OF_SCOPE,
        "composite_methodology": _COMPOSITE_NOTE,
    }
    if authed:
        result["feedback_totals"] = {
            "dispositions": fb.get("total_dismissals", 0),
            "true_positive_signal_hits": fb.get("total_tp_signals", 0),
            "false_positive_signal_hits": fb.get("total_fp_signals", 0),
        }
    return result
