// Client-side model list for MFI's "Ask HAL" picker (HAL_SPEC.md §3c).
//
// MIRROR — not the source of truth. backend/core/hal_models.py is authoritative
// and owns resolve_model(); the backend and frontend are separate projects, so
// this list exists only to render the buttons. Keep the ids in step with it.
//
// The id below travels to /hal/chat as a plain string and is validated there, so
// an edited localStorage value cannot pick an arbitrary model — it falls back to
// the default.

export type HalModelId = 'haiku' | 'sonnet'

export const HAL_MODELS: { id: HalModelId; label: string; note: string }[] = [
  { id: 'haiku', label: 'HAIKU', note: 'fast · cheapest' },
  { id: 'sonnet', label: 'SONNET', note: 'slower · best copy' },
]

export const DEFAULT_MODEL_ID: HalModelId = 'haiku'

// The SAME key every HAL surface uses, so Dave's choice follows him between HALs.
export const MODEL_STORAGE_KEY = 'hal-model'

export function getSelectedModel(): HalModelId {
  try {
    const v = localStorage.getItem(MODEL_STORAGE_KEY)
    if (v === 'haiku' || v === 'sonnet') return v
  } catch {
    /* storage blocked (private mode / embedded frame) — fall through */
  }
  return DEFAULT_MODEL_ID
}
