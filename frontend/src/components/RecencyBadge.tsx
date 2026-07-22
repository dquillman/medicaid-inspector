// Data-recency badge — one component, used on the Fraud Brain board, the
// Review Queue, and the provider detail page so "stale" reads identically
// everywhere. Annotation only: recency is NEVER a scoring input.
//
// Meaning:
//   fresh   — within 6 months of the newest data → likely still active
//   aging   — 6–24 months behind
//   stale   — >24 months behind → a recovery lead (FCA reaches back 6 years),
//             not necessarily an active scheme. NOT "innocent".
//   expired — last claim >6 years ago → likely PAST the FCA recovery window;
//             neither an active scheme nor a clean recovery. Separated out so
//             it stops crowding the recoverable stale cases under one badge.
// fresh/aging/stale are dataset-relative (a T-MSIS extract trails today, so
// they measure against the newest claim month in the data); expired is
// calendar-based (the real 6-year statute clock). Fresh renders nothing:
// absence of a warning is the signal.

export type Recency = 'fresh' | 'aging' | 'stale' | 'expired' | null | undefined

export default function RecencyBadge({
  recency,
  lastActiveMonth,
  dataAgeMonths,
}: {
  recency: Recency
  lastActiveMonth?: string | null
  dataAgeMonths?: number | null
}) {
  if (recency !== 'stale' && recency !== 'aging' && recency !== 'expired') return null

  const ageText =
    lastActiveMonth
      ? `Last claim ${lastActiveMonth}${dataAgeMonths != null ? ` (${dataAgeMonths} months ago)` : ''}`
      : 'Older claims data'

  if (recency === 'expired') {
    return (
      <span
        className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-red-400 border border-red-500/50 bg-red-500/10"
        title={`${ageText} — over 6 years old, likely past the FCA recovery window. Neither active nor a clean recovery; verify before pursuing.`}
      >
        Expired
      </span>
    )
  }
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
