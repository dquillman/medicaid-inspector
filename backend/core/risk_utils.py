"""
Shared risk tier classification utility.

Provides a single source of truth for mapping risk scores to
human-readable labels and display colors.
"""


def classify_risk(score: float) -> tuple[str, str]:
    """Return (label, color) for a given composite risk score.

    Thresholds:
        >= 75  ->  CRITICAL
        >= 50  ->  HIGH RISK
        >= 25  ->  ELEVATED
        <  25  ->  LOW RISK
    """
    if score >= 75:
        return "CRITICAL — Immediate Referral Recommended", "#991b1b"
    elif score >= 50:
        return "HIGH RISK — Investigation Required", "#9a3412"
    elif score >= 25:
        return "ELEVATED — Further Review Warranted", "#854d0e"
    else:
        return "LOW RISK", "#166534"


def risk_tier_short(score: float) -> str:
    """Return a short tier label — aligned with classify_risk thresholds."""
    if score >= 75:
        return "CRITICAL"
    elif score >= 50:
        return "HIGH"
    elif score >= 25:
        return "ELEVATED"
    else:
        return "LOW"


def risk_tier_description(score: float) -> str:
    """Return a prose description of the risk tier for narrative use."""
    if score >= 75:
        return (
            "warrants immediate investigation and potential referral to the "
            "Medicaid Fraud Control Unit (MFCU)"
        )
    elif score >= 50:
        return "warrants enhanced scrutiny and detailed claims-level audit"
    elif score >= 25:
        return "warrants routine monitoring and periodic review"
    else:
        return "is below the standard investigation threshold"
