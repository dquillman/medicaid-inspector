/**
 * Case-ledger status (queue_status) — where a provider sits in the investigation
 * pipeline. Human-set, audited, decoupled from the Fraud Brain score (the Brain
 * reads it ONE-WAY to badge/de-prioritise; it never writes it or feeds the score).
 *
 * The pipeline is one linear track with a single off-ramp:
 *
 *     New → Investigating → Confirmed → Reported
 *                         └──────────────→ Dismissed (off-ramp: not fraud)
 *
 *   New           the case landed on the board; nobody has worked it yet
 *   Investigating you're actively working it
 *   Confirmed     you've verified it IS fraud
 *   Reported      you've reported confirmed fraud to the authorities —
 *                 OIG hotline tip AND MFCU referral (all fraud goes to both)
 *   Dismissed     you've determined it is NOT fraud / not worth pursuing — closed
 *
 * `confirmed` precedes `reported` (you confirm fraud, THEN report it). The old
 * split of "Tip Filed" vs "Referred" is collapsed into one "Reported" stage —
 * confirmed fraud goes to both OIG and MFCU, so they're one step, not a choice.
 * The backend value `tip_filed` is legacy and still displays as "Reported".
 */

// The pipeline stages, in order. Each is a distinct backend queue_status value.
// This drives the dropdown, the tabs, and the lifecycle order. `reported` maps
// to the backend value `referred`.
export const CASE_STAGES = [
  { value: 'open',         label: 'New',           blurb: 'On the board, not yet worked' },
  { value: 'under_review', label: 'Investigating', blurb: 'You are actively working it' },
  { value: 'confirmed',    label: 'Confirmed',     blurb: 'Verified as fraud' },
  { value: 'referred',     label: 'Reported',      blurb: 'Filed with OIG + referred to MFCU' },
  { value: 'dismissed',    label: 'Dismissed',     blurb: 'Not fraud — closed (trains the model)' },
  { value: 'archived',     label: 'Archived',      blurb: 'Closed without judgment — never trains the model' },
] as const

export const QUEUE_STATUS_ORDER = CASE_STAGES.map(s => s.value)

export type QueueStatus = 'open' | 'under_review' | 'confirmed' | 'referred' | 'tip_filed' | 'dismissed' | 'archived'

// Display label for any backend value (incl. legacy `tip_filed` → "Reported").
export const QUEUE_STATUS_LABELS: Record<string, string> = {
  open:         'New',
  under_review: 'Investigating',
  confirmed:    'Confirmed',
  referred:     'Reported',
  tip_filed:    'Reported',   // legacy value — same meaning as referred now
  dismissed:    'Dismissed',
  archived:     'Archived',
}

// Colours track the progression: neutral → active → fraud(red) → done(green) → closed(grey).
export const QUEUE_STATUS_COLORS: Record<string, string> = {
  open:         'text-slate-300 border-slate-400/40 bg-slate-400/10',
  under_review: 'text-blue-400 border-blue-400/50 bg-blue-400/10',
  confirmed:    'text-red-400 border-red-400/60 bg-red-400/10',
  referred:     'text-emerald-400 border-emerald-400/50 bg-emerald-400/10',
  tip_filed:    'text-emerald-400 border-emerald-400/50 bg-emerald-400/10',
  dismissed:    'text-gray-500 border-gray-500/40 bg-gray-500/10',
  archived:     'text-gray-600 border-gray-600/40 bg-gray-600/10',
}

export function queueStatusLabel(status: string): string {
  return QUEUE_STATUS_LABELS[status] ?? status
}
