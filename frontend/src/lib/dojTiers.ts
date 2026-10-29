export const DOJ_TIERS: { tier: 1 | 2 | 3; label: string; blurb: string; style: string }[] = [
  { tier: 1, label: 'Your worked cases', blurb: 'Confirmed by you, or already reported to OIG / an MFCU, and not yet sent to DOJ.',
    style: 'bg-emerald-950/60 border-emerald-800 text-emerald-300' },
  { tier: 2, label: 'Paid while barred', blurb: 'Paid while on the exclusion list, after a Medicare revocation, or under a dead NPI. Each row says which. Verify identity, program, dates, and enrollment before drawing conclusions.',
    style: 'bg-red-950/60 border-red-800 text-red-300' },
  { tier: 3, label: 'Brain leads (DOJ areas)', blurb: 'Statistical suspicion in a DOJ priority area. Needs more checking before you file.',
    style: 'bg-slate-800/60 border-slate-700 text-slate-300' },
]

/** Exclusion findings: the excluded party itself, or work it did for another biller. */
export const EXCLUSION_KINDS = new Set(['active_exclusion', 'excluded_servicing'])

/**
 * The badge one shortlist row shows. Tier 2 used to say "Status discrepancies"
 * on every row, so a provider paid while on the federal exclusion list looked
 * the same as a paperwork mismatch (v3.63.0).
 */
export function rowBadge(lead: { tier: 1 | 2 | 3; kind?: string }): { label: string; style: string } {
  const t = DOJ_TIERS[lead.tier - 1]
  if (lead.tier !== 2) return { label: t.label, style: t.style }
  if (lead.kind && EXCLUSION_KINDS.has(lead.kind)) {
    return { label: 'Paid while excluded', style: 'bg-red-950/60 border-red-800 text-red-300' }
  }
  return { label: 'Status discrepancy', style: 'bg-amber-950/60 border-amber-800 text-amber-300' }
}
