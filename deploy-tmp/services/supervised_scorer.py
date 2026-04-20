"""
Supervised ML Fraud Scoring — Gradient Boosting classifier trained on
confirmed fraud/cleared labels from the review queue.

Uses scikit-learn's GradientBoostingClassifier to learn from human-reviewed
labels and predict fraud probability for unreviewed providers.
"""
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Module-level state
_model = None  # trained sklearn model
_scaler = None  # fitted StandardScaler
_training_metrics: dict = {}
_feature_names: list[str] = []
_predictions: dict[str, dict] = {}  # NPI -> prediction dict

# Features extracted from provider data
FEATURE_COLS = [
    "total_paid",
    "total_claims",
    "total_beneficiaries",
    "revenue_per_beneficiary",
    "claims_per_beneficiary",
    "active_months",
    "distinct_hcpcs",
    "avg_per_claim",
    "flag_count",
    "risk_score",
    # Individual signal scores (17 signals)
    "sig_billing_concentration",
    "sig_revenue_per_bene_outlier",
    "sig_claims_per_bene_anomaly",
    "sig_billing_ramp_rate",
    "sig_bust_out_pattern",
    "sig_ghost_billing",
    "sig_total_spend_outlier",
    "sig_billing_consistency",
    "sig_bene_concentration",
    "sig_upcoding_pattern",
    "sig_address_cluster_risk",
    "sig_oig_excluded",
    "sig_specialty_mismatch",
    "sig_corporate_shell_risk",
    "sig_geographic_impossibility",
    "sig_dead_npi_billing",
    "sig_new_provider_explosion",
]

# Map signal name -> feature column name
SIGNAL_TO_FEATURE = {
    "billing_concentration": "sig_billing_concentration",
    "revenue_per_bene_outlier": "sig_revenue_per_bene_outlier",
    "claims_per_bene_anomaly": "sig_claims_per_bene_anomaly",
    "billing_ramp_rate": "sig_billing_ramp_rate",
    "bust_out_pattern": "sig_bust_out_pattern",
    "ghost_billing": "sig_ghost_billing",
    "total_spend_outlier": "sig_total_spend_outlier",
    "billing_consistency": "sig_billing_consistency",
    "bene_concentration": "sig_bene_concentration",
    "upcoding_pattern": "sig_upcoding_pattern",
    "address_cluster_risk": "sig_address_cluster_risk",
    "oig_excluded": "sig_oig_excluded",
    "specialty_mismatch": "sig_specialty_mismatch",
    "corporate_shell_risk": "sig_corporate_shell_risk",
    "geographic_impossibility": "sig_geographic_impossibility",
    "dead_npi_billing": "sig_dead_npi_billing",
    "new_provider_explosion": "sig_new_provider_explosion",
}


def _extract_features(provider: dict) -> list[float]:
    """Extract feature vector from a provider dict."""
    signal_results = provider.get("signal_results") or []
    signal_scores: dict[str, float] = {}
    for s in signal_results:
        sig_name = s.get("signal", "")
        signal_scores[sig_name] = float(s.get("score", 0))

    flag_count = len([s for s in signal_results if s.get("flagged")])
    total_claims = float(provider.get("total_claims") or 0)
    total_paid = float(provider.get("total_paid") or 0)
    avg_per_claim = (total_paid / total_claims) if total_claims > 0 else 0

    row = [
        total_paid,
        total_claims,
        float(provider.get("total_beneficiaries") or 0),
        float(provider.get("revenue_per_beneficiary") or 0),
        float(provider.get("claims_per_beneficiary") or 0),
        float(provider.get("active_months") or 0),
        float(provider.get("distinct_hcpcs") or 0),
        avg_per_claim,
        float(flag_count),
        float(provider.get("risk_score") or 0),
    ]

    # Append individual signal scores
    for sig_name, feat_name in SIGNAL_TO_FEATURE.items():
        row.append(signal_scores.get(sig_name, 0.0))

    return row


def train_model() -> dict:
    """
    Train a supervised classifier using labeled data from the review queue.
    Labels: confirmed_fraud / referred = positive (fraud), cleared = negative.
    Returns training summary with metrics.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import cross_val_predict, StratifiedKFold
        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score,
            f1_score, roc_auc_score, confusion_matrix,
        )
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "scikit-learn is not installed. Run: pip install scikit-learn"
        )

    from core.review_store import get_review_queue
    from core.store import get_prescanned

    # Gather labeled data from review queue
    all_review = get_review_queue()
    positive_statuses = {"confirmed_fraud", "referred"}
    negative_statuses = {"dismissed"}

    labeled_npis: dict[str, int] = {}
    for item in all_review:
        status = item.get("status", "")
        npi = item.get("npi", "")
        if not npi:
            continue
        if status in positive_statuses:
            labeled_npis[npi] = 1
        elif status in negative_statuses:
            labeled_npis[npi] = 0

    total_labeled = len(labeled_npis)
    positive_count = sum(1 for v in labeled_npis.values() if v == 1)
    negative_count = total_labeled - positive_count

    if total_labeled < 10:
        return {
            "trained": False,
            "error": f"Insufficient labeled samples: {total_labeled} found, minimum 10 required. "
                     f"Mark more providers as 'confirmed_fraud'/'referred' or 'dismissed' in the Review Queue.",
            "positive_count": positive_count,
            "negative_count": negative_count,
            "total_labeled": total_labeled,
        }

    if positive_count < 2 or negative_count < 2:
        return {
            "trained": False,
            "error": f"Need at least 2 samples per class. Currently: {positive_count} fraud, {negative_count} cleared.",
            "positive_count": positive_count,
            "negative_count": negative_count,
            "total_labeled": total_labeled,
        }

    # Build feature matrix from prescan cache (has full provider data)
    providers = get_prescanned()
    provider_map = {p["npi"]: p for p in providers if p.get("npi")}

    # Also merge review queue items (they have signal_results too)
    review_map = {item["npi"]: item for item in all_review if item.get("npi")}

    X_list: list[list[float]] = []
    y_list: list[int] = []
    npis_used: list[str] = []

    for npi, label in labeled_npis.items():
        # Prefer prescan data (richer), fall back to review queue data
        pdata = provider_map.get(npi) or review_map.get(npi)
        if not pdata:
            continue
        features = _extract_features(pdata)
        X_list.append(features)
        y_list.append(label)
        npis_used.append(npi)

    if len(X_list) < 10:
        return {
            "trained": False,
            "error": f"Only {len(X_list)} labeled providers found in scan data (need 10+). "
                     "Ensure labeled providers have been scanned.",
            "positive_count": positive_count,
            "negative_count": negative_count,
            "total_labeled": total_labeled,
        }

    X = np.array(X_list)
    y = np.array(y_list)

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train model
    model = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        min_samples_split=max(2, len(X_list) // 10),
        min_samples_leaf=max(1, len(X_list) // 20),
        random_state=42,
    )

    # Cross-validated predictions for metrics
    n_splits = min(5, min(sum(y == 0), sum(y == 1)))
    if n_splits >= 2:
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        try:
            cv_proba = cross_val_predict(model, X_scaled, y, cv=cv, method="predict_proba")
            cv_preds = (cv_proba[:, 1] >= 0.5).astype(int)

            accuracy = round(float(accuracy_score(y, cv_preds)), 4)
            precision = round(float(precision_score(y, cv_preds, zero_division=0)), 4)
            recall = round(float(recall_score(y, cv_preds, zero_division=0)), 4)
            f1 = round(float(f1_score(y, cv_preds, zero_division=0)), 4)
            try:
                auc = round(float(roc_auc_score(y, cv_proba[:, 1])), 4)
            except ValueError:
                auc = None
            cm = confusion_matrix(y, cv_preds).tolist()
        except Exception as e:
            log.warning("Cross-validation failed: %s, training without CV metrics", e)
            accuracy = precision = recall = f1 = auc = None
            cm = None
    else:
        accuracy = precision = recall = f1 = auc = None
        cm = None

    # Fit final model on all labeled data
    model.fit(X_scaled, y)

    # Feature importances
    importances = model.feature_importances_
    feature_imp = {}
    for i, name in enumerate(FEATURE_COLS):
        feature_imp[name] = round(float(importances[i]), 4)

    # Sort by importance
    feature_imp_sorted = dict(sorted(feature_imp.items(), key=lambda x: x[1], reverse=True))

    # Store model
    global _model, _scaler, _training_metrics, _feature_names, _predictions
    _model = model
    _scaler = scaler
    _feature_names = list(FEATURE_COLS)

    _training_metrics = {
        "trained": True,
        "trained_at": time.time(),
        "total_labeled": len(X_list),
        "positive_count": int(sum(y == 1)),
        "negative_count": int(sum(y == 0)),
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "auc": auc,
        "confusion_matrix": cm,
        "feature_importance": feature_imp_sorted,
        "cv_folds": n_splits if n_splits >= 2 else 0,
    }

    # Score all providers
    _predictions = {}
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue
        try:
            feats = _extract_features(p)
            feats_scaled = scaler.transform([feats])
            proba = model.predict_proba(feats_scaled)[0]
            fraud_prob = round(float(proba[1]), 4)
            _predictions[npi] = {
                "npi": npi,
                "fraud_probability": fraud_prob,
                "label": labeled_npis.get(npi),  # None if unlabeled
            }
        except Exception as e:
            log.debug("Could not score NPI %s: %s", npi, e)

    log.info(
        "Supervised model trained: %d samples (%d fraud, %d clear), scored %d providers",
        len(X_list), int(sum(y == 1)), int(sum(y == 0)), len(_predictions),
    )

    return {
        **_training_metrics,
        "providers_scored": len(_predictions),
    }


def predict_fraud_probability(npi: str) -> Optional[dict]:
    """Return fraud probability for a specific provider."""
    if _model is None:
        return {"error": "Model not trained yet. Call POST /api/ml/supervised/train first."}

    # Check cached predictions first
    if npi in _predictions:
        return _predictions[npi]

    # Try to score on the fly
    from core.store import get_provider_by_npi
    pdata = get_provider_by_npi(npi)
    if not pdata:
        return {"error": f"NPI {npi} not found in scanned providers."}

    try:
        feats = _extract_features(pdata)
        feats_scaled = _scaler.transform([feats])
        proba = _model.predict_proba(feats_scaled)[0]
        fraud_prob = round(float(proba[1]), 4)
        result = {
            "npi": npi,
            "fraud_probability": fraud_prob,
            "label": None,
        }
        _predictions[npi] = result
        return result
    except Exception as e:
        return {"error": str(e)}


def get_model_status() -> dict:
    """Return current model status and metrics."""
    if not _training_metrics:
        return {
            "trained": False,
            "message": "Supervised model not trained yet. Call POST /api/ml/supervised/train.",
        }
    return {
        **_training_metrics,
        "providers_scored": len(_predictions),
    }


def get_feature_importance() -> dict:
    """Return ranked feature importances from the trained model."""
    if not _training_metrics or not _training_metrics.get("feature_importance"):
        return {"error": "Model not trained yet.", "features": []}

    fi = _training_metrics["feature_importance"]
    features = [{"feature": k, "importance": v} for k, v in fi.items()]
    return {"features": features}


def get_all_predictions(limit: int = 100, offset: int = 0) -> dict:
    """Return all provider predictions ranked by fraud probability."""
    if _model is None:
        return {"error": "Model not trained yet.", "predictions": [], "total": 0}

    sorted_preds = sorted(
        _predictions.values(),
        key=lambda x: x.get("fraud_probability", 0),
        reverse=True,
    )

    total = len(sorted_preds)
    page = sorted_preds[offset:offset + limit]

    # Enrich with provider names
    from core.store import get_prescanned
    providers = get_prescanned()
    name_map = {p["npi"]: p.get("provider_name", "") for p in providers if p.get("npi")}
    state_map = {p["npi"]: p.get("state", "") for p in providers if p.get("npi")}
    paid_map = {p["npi"]: p.get("total_paid", 0) for p in providers if p.get("npi")}
    risk_map = {p["npi"]: p.get("risk_score", 0) for p in providers if p.get("npi")}

    enriched = []
    for pred in page:
        npi = pred["npi"]
        enriched.append({
            **pred,
            "provider_name": name_map.get(npi, ""),
            "state": state_map.get(npi, ""),
            "total_paid": paid_map.get(npi, 0),
            "risk_score": risk_map.get(npi, 0),
        })

    return {
        "predictions": enriched,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
