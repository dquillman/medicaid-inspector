// Data-recency badge — one component, used on the Fraud Brain board, the
// Review Queue, and the provider detail page so "stale" reads identically
// everywhere. Annotation only: recency is NEVER a scoring input.
//
// Meaning (dataset-relative, not wall-clock — a T-MSIS extract always trails
// today, so the badge measures against the newest claim month in the data):
//   fresh  — within 6 months of the newest data → likely still active
//   aging  — 6–24 months behind
//   stale  — >24 months behind → a recovery lead (FCA reaches back 6 years),
//            not necessarily an active scheme. NOT "innocent".
// Fresh deliberately renders nothing: absence of a warning is the signal.

export type Recency = 'fresh' | 'aging' | 'stale' | null | undefined

export default function RecencyBadge({
  recency,
  lastActiveMonth,
  dataAgeMonths,
}: {
  recency: Recency
  lastActiveMonth?: string | null
  dataAgeMonths?: number | null
}) {
  if (recency !== 'stale' && recency !== 'aging') return null

  const ageText =
    lastActiveMonth
      ? `Last claim ${lastActiveMonth}${dataAgeMonths != null ? ` (${dataAgeMonths} months ago)` : ''}`
      : 'Older claims data'

  if (recency === 'stale') {
    return (
      <span
        className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-amber-400 border border-amber-500/50 bg-amber-500/10"
        title={`${ageText} — recovery lead, not an active scheme`}
      >
        Stale
      </span>
    )
  }
  return (
    <span
      className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-ink-tertiary border border-hairline bg-surface-2"
      title={ageText}
    >
      Aging
    </span>
  )
}
