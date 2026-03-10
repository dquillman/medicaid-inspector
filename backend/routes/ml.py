"""
Supervised ML model API routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_admin

router = APIRouter(prefix="/api/ml/supervised", tags=["ml-supervised"], dependencies=[Depends(require_admin)])


@router.post("/train")
async def train_supervised_model():
    """Train gradient boosting classifier from review queue labels."""
    from services.supervised_scorer import train_model
    try:
        result = train_model()
        return result
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        raise HTTPException(500, f"Training failed: {e}")


@router.get("/status")
async def supervised_model_status():
    """Return supervised model status, metrics, and sample counts."""
    from services.supervised_scorer import get_model_status
    return get_model_status()


@router.get("/feature-importance")
async def feature_importance():
    """Return ranked feature importances from the trained model."""
    from services.supervised_scorer import get_feature_importance
    return get_feature_importance()


@router.get("/predict/{npi}")
async def predict_provider(npi: str):
    """Get fraud probability for a specific provider."""
    from services.supervised_scorer import predict_fraud_probability
    result = predict_fraud_probability(npi)
    if result and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/predictions")
async def all_predictions(limit: int = 100, offset: int = 0):
    """Ranked list of all scanned providers by fraud probability."""
    from services.supervised_scorer import get_all_predictions
    result = get_all_predictions(limit=limit, offset=offset)
    if "error" in result and not result.get("predictions"):
        raise HTTPException(400, result["error"])
    return result
