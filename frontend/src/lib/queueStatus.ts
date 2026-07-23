/**
 * Case-ledger status (queue_status) — where a provider sits in the investigation
 * pipeline. Human-set, audited, decoupled from the Fraud Brain score (the Brain
 * reads it ONE-WAY to badge/de-prioritise; it never writes it or feeds the score).
 *
 * The pipeline is one linear track with two reporting settings and off-ramps:
 *
 *     New → Investigating → Confirmed → Reported: OIG → Reported: MFCU
 *                         └──────────────→ Dismissed / Archived (off-ramps)
 *
 *   New            the case landed on the board; nobody has worked it yet
 *   Investigating  you're actively working it
 *   Confirmed      you've verified it IS fraud
 *   Reported: OIG  tip filed with the federal HHS-OIG hotline (tip_filed)
 *   Reported: MFCU referred to the state Medicaid Fraud Control Unit (referred)
 *   Dismissed      NOT fraud — closed (negative training label)
 *   Archived       closed without judgment — never a training label
 *
 * `confirmed` precedes reporting (verify fraud, THEN report it). Reporting is
 * TWO distinct settings because they're different channels with different
 * weight: the OIG tip is the federal lead; the MFCU referral is the state
 * enforcement handoff. A case filed with both carries the most recent one as
 * its status — set OIG first, then MFCU; the audit trail records each step.
 */

// The pipeline stages, in order. Each is a distinct backend queue_status value.
// This drives the dropdown, the tabs, and the lifecycle order.
export const CASE_STAGES = [
  { value: 'open',         label: 'New',            blurb: 'On the board, not yet worked' },
  { value: 'under_review', label: 'Investigating',  blurb: 'You are actively working it' },
  { value: 'confirmed',    label: 'Confirmed',      blurb: 'Verified as fraud' },
  { value: 'tip_filed',    label: 'Reported: OIG',  blurb: 'Tip filed with the HHS-OIG hotline' },
  { value: 'referred',     label: 'Reported: MFCU', blurb: 'Referred to the state Medicaid Fraud Control Unit. If you file both, set OIG first, then MFCU — the History keeps each step' },
  { value: 'dismissed',    label: 'Dismissed',      blurb: 'Not fraud — closed (trains the model)' },
  { value: 'archived',     label: 'Archived',       blurb: 'Closed without judgment — never trains the model' },
] as const

export const QUEUE_STATUS_ORDER = CASE_STAGES.map(s => s.value)

export type QueueStatus = 'open' | 'under_review' | 'confirmed' | 'referred' | 'tip_filed' | 'dismissed' | 'archived'

// Display label for any backend value. Reporting is TWO distinct settings:
// tip_filed = the federal OIG hotline tip; referred = the state MFCU referral.
// A case reported to both carries the most recent one as its status — the
// audit trail records each transition, so nothing is lost.
export const QUEUE_STATUS_LABELS: Record<string, string> = {
  open:         'New',
  under_review: 'Investigating',
  confirmed:    'Confirmed',
  tip_filed:    'Reported: OIG',
  referred:     'Reported: MFCU',
  dismissed:    'Dismissed',
  archived:     'Archived',
}

// Colours track the progression: neutral → active → fraud(red) → reported
// (teal = federal OIG tip, emerald = state MFCU referral) → closed(grey).
export const QUEUE_STATUS_COLORS: Record<string, string> = {
  open:         'text-slate-300 border-slate-400/40 bg-slate-400/10',
  under_review: 'text-blue-400 border-blue-400/50 bg-blue-400/10',
  confirmed:    'text-red-400 border-red-400/60 bg-red-400/10',
  tip_filed:    'text-teal-300 border-teal-400/50 bg-teal-400/10',
  referred:     'text-emerald-400 border-emerald-400/50 bg-emerald-400/10',
  dismissed:    'text-gray-500 border-gray-500/40 bg-gray-500/10',
  archived:     'text-gray-600 border-gray-600/40 bg-gray-600/10',
}

export function queueStatusLabel(status: string): string {
  return QUEUE_STATUS_LABELS[status] ?? status
}
