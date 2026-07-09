/**
 * Case-ledger status (queue_status) — the human-gated disposition of an NPI in
 * the Review Queue, DISTINCT from the granular workflow `status` and from the
 * live-computed Fraud Brain score.
 *
 * The Fraud Brain reads this ONE-WAY, read-only, purely to badge / de-prioritise
 * already-actioned providers. It never writes it and it never feeds the score.
 */
export const QUEUE_STATUS_ORDER = [
  'open',
  'under_review',
  'tip_filed',
  'confirmed',
  'referred',
  'dismissed',
] as const

export type QueueStatus = (typeof QUEUE_STATUS_ORDER)[number]

export const QUEUE_STATUS_LABELS: Record<string, string> = {
  open:         'In Review',
  under_review: 'Under Review',
  tip_filed:    'Tip Filed',
  confirmed:    'Confirmed',
  referred:     'Referred',
  dismissed:    'Dismissed',
}

export const QUEUE_STATUS_COLORS: Record<string, string> = {
  open:         'text-cyan-400 border-cyan-400/50 bg-cyan-400/10',
  under_review: 'text-purple-400 border-purple-400/50 bg-purple-400/10',
  tip_filed:    'text-amber-400 border-amber-400/50 bg-amber-400/10',
  confirmed:    'text-red-400 border-red-400/60 bg-red-400/10',
  referred:     'text-orange-400 border-orange-400/50 bg-orange-400/10',
  dismissed:    'text-gray-500 border-gray-500/40 bg-gray-500/10',
}

export function queueStatusLabel(status: string): string {
  return QUEUE_STATUS_LABELS[status] ?? status
}
