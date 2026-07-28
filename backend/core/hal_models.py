"""Model registry for MFI's "Ask HAL" (HAL_SPEC.md §3c).

Every HAL surface must let Dave pick the model per turn, and the pick must be
resolved SERVER-side so a deployment pin always outranks the browser. This is the
Python port of the reference registry, qcode/src/lib/hal-models.ts — keep them in
step; the ids and API strings must match, because MFI can also RELAY a turn to
qcode and the same id has to mean the same model on both sides.

MFI answers on two paths (see routes/hal.py): its own local expert loop, and the
qcode relay. Both take the model from resolve_model(), so the choice behaves
identically whichever path serves the turn.
"""
from typing import Optional
import os

# id -> (label, api model string, cost note shown under the button)
HAL_MODELS = [
    {"id": "haiku", "label": "HAIKU", "api": "claude-haiku-4-5-20251001", "note": "fast · cheapest"},
    {"id": "sonnet", "label": "SONNET", "api": "claude-sonnet-5", "note": "slower · best copy"},
]

DEFAULT_MODEL_ID = "haiku"
MODEL_STORAGE_KEY = "hal-model"  # the same localStorage key on every HAL surface

_API_BY_ID = {m["id"]: m["api"] for m in HAL_MODELS}
_VALID_API = {m["api"] for m in HAL_MODELS}


def resolve_model(requested: Optional[str] = None, env_override: Optional[str] = None) -> str:
    """Resolve a client-requested model into a real Anthropic model string.

    Precedence: the HAL_MODEL env pin wins, then a valid UI request, then Haiku.
    A deployment-level pin is a policy and cost control, so a browser request must
    never bypass it. An unrecognised id falls back to the default rather than being
    forwarded to the API.
    """
    pin = env_override if env_override is not None else os.environ.get("HAL_MODEL")
    if pin and pin.strip():
        return pin.strip()
    if isinstance(requested, str):
        if requested in _API_BY_ID:
            return _API_BY_ID[requested]
        if requested in _VALID_API:
            return requested
    return _API_BY_ID[DEFAULT_MODEL_ID]
