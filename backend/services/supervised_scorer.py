"""
Supervised ML Fraud Scoring — Gradient Boosting classifier trained on
confirmed fraud/cleared labels from the review queue.

Uses scikit-learn's GradientBoostingClassifier to learn from human-reviewed
labels and predict fraud probability for unreviewed providers.
"""
import json
import logging
import pathlib
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

# Module-level state — protected by _lock for thread safety
_lock = threading.Lock()
_model = None  # trained sklearn model
_scaler = None  # fitted StandardScaler
_training_metrics: dict = {}
_feature_names: list[str] = []
_predictions: dict[str, dict] = {}  # NPI -> prediction dict

# Metrics + predictions persist as JSON (synced through GCS) so the trained
# state survives Cloud Run restarts. The sklearn model object itself is NOT
# persisted — the predictions dict covers every scanned provider, and pickled
# models are fragile across sklearn versions. On-the-fly scoring of brand-new
# NPIs needs a retrain after a restart; everything else works from the JSON.
_PERSIST_PATH = pathlib.Path(__file__).parent.parent / "supervised_model.json"
_load_attempted = False


def _persist_state(metrics: dict, feature_names: list[str], predictions: dict[str, dict]) -> None:
    try:
        tmp = _PERSIST_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"training_metrics": metrics, "feature_names": feature_names, "predictions": predictions},
                f, separators=(",", ":"),
            )
        tmp.replace(_PERSIST_PATH)
        from core.gcs_sync import upload_file
        upload_file(_PERSIST_PATH.name)
    except Exception as e:
        log.warning("Could not persist supervised model state: %s", e)


def _ensure_loaded() -> None:
    """Restore persisted metrics/predictions on first read after a restart."""
    global _load_attempted, _training_metrics, _feature_names, _predictions
    with _lock:
        if _load_attempted or _training_metrics:
            return
        _load_attempted = True
    if not _PERSIST_PATH.exists():
        return
    try:
        with open(_PERSIST_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        with _lock:
            if not _training_metrics:  # don't clobber a fresher in-memory train
                _training_metrics = saved.get("training_metrics") or {}
                _feature_names = saved.get("feature_names") or []
                _predictions = saved.get("predictions") or {}
        log.info("Restored supervised model state: %d predictions", len(_predictions))
    except Exception as e:
        log.warning("Could not restore supervised model state: %s", e)

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
    # Full cache uses signal_results (with scores); slim cache uses flags (with flagged bool).
    # Merge both so feature extraction works with either cache format.
    signal_results = provider.get("signal_results") or []
    flags = provider.get("flags") or []
    signal_scores: dict[str, float] = {}
    for s in signal_results:
        sig_name = s.get("signal", "")
        signal_scores[sig_name] = float(s.get("score", 0))
    # Fill in flagged signals from slim-cache flags if not already in signal_results
    for f in flags:
        sig_name = f.get("signal", "")
        if sig_name and sig_name not in signal_scores:
            # Use flagged as a binary score (1.0 = flagged)
            signal_scores[sig_name] = 1.0 if f.get("flagged") else 0.0

    # Use flag_count from provider if available (slim cache stores it directly)
    explicit_flag_count = provider.get("flag_count")
    if explicit_flag_count is not None:
        flag_count = int(explicit_flag_count)
    else:
        flag_count = len([s for s in (signal_results + flags) if s.get("flagged")])
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

    # Build training metrics locally before the atomic swap
    new_feature_names = list(FEATURE_COLS)
    new_training_metrics = {
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

    # Score all providers into a local dict before the atomic swap
    new_predictions: dict[str, dict] = {}
    for p in providers:
        npi = p.get("npi")
        if not npi:
            continue
        try:
            feats = _extract_features(p)
            feats_scaled = scaler.transform([feats])
            proba = model.predict_proba(feats_scaled)[0]
            fraud_prob = round(float(proba[1]), 4)
            new_predictions[npi] = {
                "npi": npi,
                "fraud_probability": fraud_prob,
                "label": labeled_npis.get(npi),  # None if unlabeled
            }
        except Exception as e:
            log.debug("Could not score NPI %s: %s", npi, e)

    log.info(
        "Supervised model trained: %d samples (%d fraud, %d clear), scored %d providers",
        len(X_list), int(sum(y == 1)), int(sum(y == 0)), len(new_predictions),
    )

    # Atomic swap — readers see either old complete state or new complete state
    global _model, _scaler, _training_metrics, _feature_names, _predictions
    with _lock:
        _model = model
        _scaler = scaler
        _feature_names = new_feature_names
        _training_metrics = new_training_metrics
        _predictions = new_predictions

    _persist_state(new_training_metrics, new_feature_names, new_predictions)

    return {
        **new_training_metrics,
        "providers_scored": len(new_predictions),
    }


def predict_fraud_probability(npi: str) -> Optional[dict]:
    """Return fraud probability for a specific provider."""
    _ensure_loaded()
    with _lock:
        current_model = _model
        current_scaler = _scaler
        preds_snapshot = _predictions

    # Persisted predictions work without the live model object
    if npi in preds_snapshot:
        return preds_snapshot[npi]

    if current_model is None:
        if preds_snapshot:
            return {"error": f"NPI {npi} was not scored in the last training run. Retrain to score it."}
        return {"error": "Model not trained yet. Call POST /api/ml/supervised/train first."}

    # Try to score on the fly
    from core.store import get_provider_by_npi
    pdata = get_provider_by_npi(npi)
    if not pdata:
        return {"error": f"NPI {npi} not found in scanned providers."}

    try:
        feats = _extract_features(pdata)
        feats_scaled = current_scaler.transform([feats])
        proba = current_model.predict_proba(feats_scaled)[0]
        fraud_prob = round(float(proba[1]), 4)
        result = {
            "npi": npi,
            "fraud_probability": fraud_prob,
            "label": None,
        }
        # Cache result (benign race: worst case two threads both write the same value)
        with _lock:
            _predictions[npi] = result
        return result
    except Exception as e:
        return {"error": str(e)}


def _label_readiness() -> dict:
    """Inspect the review queue for labeled samples without running training.

    Returns label counts and a can_train flag with a human-readable reason.
    Used by GET /api/ml/supervised/status so the UI can show progress toward
    the minimum training prerequisites before the user clicks Train.
    """
    from core.review_store import get_review_queue
    positive_statuses = {"confirmed_fraud", "referred"}
    negative_statuses = {"dismissed"}
    positive = 0
    negative = 0
    for item in get_review_queue():
        status = item.get("status", "")
        if not item.get("npi"):
            continue
        if status in positive_statuses:
            positive += 1
        elif status in negative_statuses:
            negative += 1
    total = positive + negative
    if total < 10:
        return {
            "total_labeled": total,
            "positive_count": positive,
            "negative_count": negative,
            "can_train": False,
            "train_blocker": (
                f"Need at least 10 labeled providers, have {total}. "
                "Mark providers as 'confirmed_fraud'/'referred' or 'dismissed' in the Review Queue."
            ),
        }
    if positive < 2 or negative < 2:
        return {
            "total_labeled": total,
            "positive_count": positive,
            "negative_count": negative,
            "can_train": False,
            "train_blocker": (
                f"Need at least 2 samples per class. "
                f"Currently {positive} fraud / {negative} cleared."
            ),
        }
    return {
        "total_labeled": total,
        "positive_count": positive,
        "negative_count": negative,
        "can_train": True,
        "train_blocker": None,
    }


def get_model_status() -> dict:
    """Return current model status and metrics."""
    _ensure_loaded()
    with _lock:
        metrics_snapshot = dict(_training_metrics)
        preds_len = len(_predictions)
    readiness = _label_readiness()
    if not metrics_snapshot:
        return {
            "trained": False,
            "message": "Supervised model not trained yet. Call POST /api/ml/supervised/train.",
            **readiness,
        }
    return {
        **metrics_snapshot,
        "providers_scored": preds_len,
        **readiness,
    }


def get_feature_importance() -> dict:
    """Return ranked feature importances from the trained model."""
    _ensure_loaded()
    with _lock:
        metrics_snapshot = dict(_training_metrics)
    if not metrics_snapshot or not metrics_snapshot.get("feature_importance"):
        return {"error": "Model not trained yet.", "features": []}

    fi = metrics_snapshot["feature_importance"]
    features = [{"feature": k, "importance": v} for k, v in fi.items()]
    return {"features": features}


def get_all_predictions(limit: int = 100, offset: int = 0) -> dict:
    """Return all provider predictions ranked by fraud probability."""
    _ensure_loaded()
    with _lock:
        preds_snapshot = dict(_predictions)
    # Persisted predictions are servable even without the live model object
    if not preds_snapshot:
        return {"error": "Model not trained yet.", "predictions": [], "total": 0}

    sorted_preds = sorted(
        preds_snapshot.values(),
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
