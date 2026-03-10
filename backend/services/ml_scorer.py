"""
ML Anomaly Detection — Isolation Forest scoring for providers.

Uses scikit-learn's IsolationForest to detect statistical anomalies
across multiple provider-level features. Complements the rule-based
risk score by surfacing providers that are statistically unusual even
if they don't trigger specific fraud signals.
"""
import logging
import time

log = logging.getLogger(__name__)

# Module-level state
_ml_scores: dict[str, dict] = {}  # keyed by NPI
_training_stats: dict = {}

# Feature columns used for the model
FEATURE_COLS = [
    "total_paid",
    "total_claims",
    "total_beneficiaries",
    "revenue_per_beneficiary",
    "claims_per_beneficiary",
    "active_months",
    "distinct_hcpcs",
    "flag_count",
]


def train_and_score() -> dict:
    """
    Pull all providers from prescan cache, build feature matrix,
    fit IsolationForest, and store anomaly scores (0-100 scale).

    Returns summary dict with count of providers scored and top anomalies.
    """
    try:
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "scikit-learn is not installed. Run: pip install scikit-learn"
        )

    from core.store import get_prescanned

    providers = get_prescanned()
    if not providers:
        return {"error": "No providers in cache — run a scan first", "scored": 0}

    if len(providers) < 10:
        return {"error": "Need at least 10 providers for meaningful ML scoring", "scored": 0}

    # Build feature matrix
    npis: list[str] = []
    features: list[list[float]] = []

    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue

        flag_count = len([s for s in (p.get("signal_results") or []) if s.get("flagged")])

        row = [
            float(p.get("total_paid") or 0),
            float(p.get("total_claims") or 0),
            float(p.get("total_beneficiaries") or 0),
            float(p.get("revenue_per_beneficiary") or 0),
            float(p.get("claims_per_beneficiary") or 0),
            float(p.get("active_months") or 0),
            float(p.get("distinct_hcpcs") or 0),
            float(flag_count),
        ]
        npis.append(npi)
        features.append(row)

    X = np.array(features)

    # Normalize features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Fit Isolation Forest
    model = IsolationForest(
        contamination=0.05,
        n_estimators=200,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    # Get anomaly scores: decision_function returns values where
    # more negative = more anomalous. Range is roughly -0.5 to 0.5.
    raw_scores = model.decision_function(X_scaled)

    # Map to 0-100 scale: most negative -> 100 (most anomalous),
    # most positive -> 0 (most normal)
    min_score = raw_scores.min()
    max_score = raw_scores.max()
    score_range = max_score - min_score if max_score != min_score else 1.0

    # Compute feature importances approximation using mean absolute
    # deviation of each feature for anomalous vs normal samples
    predictions = model.predict(X_scaled)
    anomaly_mask = predictions == -1
    normal_mask = predictions == 1

    feature_importance: dict[str, float] = {}
    for i, col in enumerate(FEATURE_COLS):
        if anomaly_mask.any() and normal_mask.any():
            anomaly_mean = np.abs(X_scaled[anomaly_mask, i]).mean()
            normal_mean = np.abs(X_scaled[normal_mask, i]).mean()
            feature_importance[col] = round(float(anomaly_mean - normal_mean), 4)
        else:
            feature_importance[col] = 0.0

    # Store per-NPI scores
    global _ml_scores, _training_stats
    _ml_scores = {}

    all_mapped_scores: list[float] = []
    for idx, npi in enumerate(npis):
        # Invert so higher = more anomalous
        mapped = ((max_score - raw_scores[idx]) / score_range) * 100.0
        mapped = round(float(mapped), 1)
        all_mapped_scores.append(mapped)

    # Compute percentiles
    sorted_scores = sorted(all_mapped_scores)
    n = len(sorted_scores)

    for idx, npi in enumerate(npis):
        score = all_mapped_scores[idx]
        # Percentile: what % of providers score below this one
        percentile = round(
            (sorted_scores.index(score) / n) * 100 if n > 0 else 0, 1
        )

        # Per-provider feature contributions (how far each feature
        # deviates from the mean in the direction of anomaly)
        provider_importances: dict[str, float] = {}
        for fi, col in enumerate(FEATURE_COLS):
            # Use absolute scaled value as contribution indicator
            provider_importances[col] = round(float(abs(X_scaled[idx, fi])), 3)

        _ml_scores[npi] = {
            "ml_anomaly_score": score,
            "ml_percentile": percentile,
            "feature_importances": provider_importances,
        }

    # Top anomalies
    top_anomalies = sorted(
        _ml_scores.items(),
        key=lambda x: x[1]["ml_anomaly_score"],
        reverse=True,
    )[:20]

    _training_stats = {
        "trained_at": time.time(),
        "provider_count": len(npis),
        "anomaly_count": int(anomaly_mask.sum()),
        "contamination": 0.05,
        "n_estimators": 200,
        "feature_cols": FEATURE_COLS,
        "global_feature_importance": feature_importance,
    }

    log.info(
        "ML model trained: %d providers, %d anomalies detected",
        len(npis),
        int(anomaly_mask.sum()),
    )

    return {
        "scored": len(npis),
        "anomalies_detected": int(anomaly_mask.sum()),
        "top_anomalies": [
            {"npi": npi, **data} for npi, data in top_anomalies
        ],
        "feature_importance": feature_importance,
    }


def get_ml_score(npi: str) -> dict:
    """Return ML anomaly score for a single provider."""
    if npi in _ml_scores:
        return _ml_scores[npi]
    return {
        "ml_anomaly_score": None,
        "ml_percentile": None,
        "feature_importances": None,
        "note": "ML model not trained yet — call POST /api/ml/train first"
        if not _ml_scores
        else f"NPI {npi} not found in ML scores",
    }


def get_ml_status() -> dict:
    """Return training stats and model status."""
    if not _training_stats:
        return {
            "trained": False,
            "message": "ML model not trained yet — call POST /api/ml/train",
        }
    return {
        "trained": True,
        **_training_stats,
        "scores_available": len(_ml_scores),
    }
