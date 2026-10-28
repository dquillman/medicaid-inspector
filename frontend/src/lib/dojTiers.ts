export const DOJ_TIERS: { tier: 1 | 2 | 3; label: string; blurb: string; style: string }[] = [
  { tier: 1, label: 'Your worked cases', blurb: 'Confirmed by you, or already reported to OIG / an MFCU, and not yet sent to DOJ.',
    style: 'bg-emerald-950/60 border-emerald-800 text-emerald-300' },
  { tier: 2, label: 'Status discrepancies', blurb: 'Billed while excluded, after a Medicare revocation, or under a dead NPI. Verify identity, program, dates, and enrollment before drawing conclusions.',
    style: 'bg-red-950/60 border-red-800 text-red-300' },
  { tier: 3, label: 'Brain leads (DOJ areas)', blurb: 'Statistical suspicion in a DOJ priority area. Needs more checking before you file.',
    style: 'bg-slate-800/60 border-slate-700 text-slate-300' },
]
