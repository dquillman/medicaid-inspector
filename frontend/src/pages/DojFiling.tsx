import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { DOJ_TIERS } from '../lib/dojTiers'
import Breadcrumbs from '../components/Breadcrumbs'
import DojTipPanel, { DOJ_PORTAL, dojTipQueryKey } from '../components/DojTipPanel'
import type { DojShortlistLead } from '../lib/types'

const RESUME_KEY = 'mfi_doj_filing_npi'

function readResume(): string | null {
  try { return localStorage.getItem(RESUME_KEY) } catch { return null }
}
function writeResume(npi: string | null) {
  try {
    if (npi) localStorage.setItem(RESUME_KEY, npi)
    else localStorage.removeItem(RESUME_KEY)
  } catch { /* private window: resume just won't persist */ }
}

/**
 * Filing mode: walk the DOJ shortlist one lead at a time. The report for the
 * current lead is ready on arrival and the NEXT one is drafted in the
 * background, so moving on never waits. The order is a snapshot taken when the
 * session starts — logging a lead must not reshuffle the leads still ahead.
 * Filing itself stays manual: the portal needs your own signed statement.
 */
export default function DojFiling() {
  const [params] = useSearchParams()
  const tierParam = Number(params.get('tier')) as 0 | 1 | 2 | 3
  const priorityOnly = params.get('priority') === '1'
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['doj-shortlist'],
    queryFn: () => api.dojShortlist(),
    staleTime: 30_000,
    gcTime: 30 * 60_000,
  })

  const [snapshot, setSnapshot] = useState<DojShortlistLead[] | null>(null)
  const [pos, setPos] = useState(0)
  const [filedCount, setFiledCount] = useState(0)

  useEffect(() => {
    if (snapshot || !data) return
    let leads = data.leads
    if (tierParam) leads = leads.filter(l => l.tier === tierParam)
    if (priorityOnly) leads = leads.filter(l => l.doj_priority_area)
    setSnapshot(leads)
    const resume = readResume()
    const at = resume ? leads.findIndex(l => l.npi === resume) : -1
    setPos(at >= 0 ? at : 0)
  }, [data, snapshot, tierParam, priorityOnly])

  const lead = snapshot?.[pos]
  const next = snapshot?.[pos + 1]

  // Only once the snapshot exists: on mount `lead` is still undefined, and
  // clearing then would erase the place this effect is meant to restore.
  useEffect(() => {
    if (!snapshot) return
    writeResume(lead?.npi ?? null)
  }, [snapshot, lead?.npi])

  // Draft the next report while this one is being filed.
  useEffect(() => {
    if (!next) return
    void queryClient.prefetchQuery({
      queryKey: dojTipQueryKey(next.npi),
      queryFn: () => api.oigTip(next.npi, 'doj'),
      staleTime: 5 * 60_000,
    })
  }, [next, queryClient])

  const total = snapshot?.length ?? 0
  const tierInfo = useMemo(() => (lead ? DOJ_TIERS[lead.tier - 1] : null), [lead])
  const go = (i: number) => {
    setPos(Math.max(0, Math.min(i, total)))
    window.scrollTo({ top: 0 })
  }

  const navBtn =
    'px-4 py-2 text-sm rounded border border-gray-600 text-gray-300 hover:bg-gray-700 disabled:opacity-40'

  return (
    <div className="space-y-5">
      <Breadcrumbs />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-200">DOJ Filing Mode</h1>
          <p className="text-sm text-gray-500 mt-1 max-w-3xl">
            One lead at a time, in shortlist order. Open the portal, paste, attach, submit, then paste
            the reference number here and log it. The next report is already being drafted. You do the
            filing &mdash; DOJ needs your own signed statement.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a href={DOJ_PORTAL} target="_blank" rel="noopener noreferrer"
             className="px-4 py-2 text-sm font-semibold rounded bg-amber-600 hover:bg-amber-500 text-black">
            Open america.gov/fraud ↗
          </a>
          <Link to="/doj-shortlist" className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200">Back to shortlist</Link>
        </div>
      </div>

      {isLoading && <div className="card h-32 flex items-center justify-center text-gray-600 text-sm">Loading the DOJ shortlist…</div>}
      {error != null && <div className="card border-red-900/60"><p className="text-sm text-red-400">Failed to load: {String(error)}</p></div>}

      {snapshot && total === 0 && (
        <div className="card"><p className="text-sm text-gray-400">No leads to file with these filters.</p></div>
      )}

      {snapshot && total > 0 && !lead && (
        <div className="card space-y-2">
          <p className="text-sm text-gray-200 font-semibold">End of the list.</p>
          <p className="text-sm text-gray-400">You logged {filedCount} filing{filedCount === 1 ? '' : 's'} this session.</p>
          <div className="flex gap-2">
            <button className={navBtn} onClick={() => go(total - 1)}>Back to the last lead</button>
            <Link to="/doj-shortlist" className={navBtn}>Back to shortlist</Link>
          </div>
        </div>
      )}

      {lead && tierInfo && (
        <>
          <div className="card space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500 font-mono">
              <span>Lead {pos + 1} of {total} &middot; shortlist #{lead.rank}</span>
              <span>Logged this session: {filedCount}</span>
            </div>
            <div className="h-1 bg-gray-800 rounded overflow-hidden">
              <div className="h-full bg-amber-500" style={{ width: `${((pos + 1) / total) * 100}%` }} />
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pt-1">
              <Link to={`/providers/${lead.npi}`} className="text-lg font-bold text-blue-300 hover:underline">
                {lead.provider_name || lead.npi}
              </Link>
              <span className="text-xs text-gray-500 font-mono">{lead.npi} &middot; {lead.state || '—'} &middot; {lead.specialty || 'specialty unknown'}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`text-[10px] px-2 py-0.5 border rounded ${tierInfo.style}`}>{tierInfo.label}</span>
              {lead.doj_priority_area && (
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-amber-400/60 bg-amber-400/10 text-amber-300">
                  DOJ priority &middot; {lead.doj_priority_area}
                </span>
              )}
              <span className="text-xs text-gray-300">{lead.reason}</span>
            </div>
            <p className="text-xs text-gray-400">
              {lead.amount_label}: <span className="font-mono text-red-400">{fmt(lead.amount)}</span>
              {' '}&middot; last billed <span className="font-mono">{lead.last_month || '—'}</span>
            </p>
            {lead.related_npis && lead.related_npis.length > 0 && (
              <p className="text-xs text-amber-300">
                Same company also bills under {lead.related_npis.join(', ')}. File ONE tip and name every NPI in it
                (add them to the short version) &mdash; DOJ pays per distinct tip.
              </p>
            )}
            {lead.caveat && <p className="text-xs text-amber-400">CHECK FIRST: {lead.caveat}</p>}
          </div>

          <DojTipPanel
            key={lead.npi}
            npi={lead.npi}
            providerName={lead.provider_name}
            providerState={lead.state}
            riskScore={lead.risk_score}
            logLabel="Log as filed & Next"
            onLogged={() => {
              setFiledCount(c => c + 1)
              setTimeout(() => go(pos + 1), 700)
            }}
            actions={
              <>
                <button className={navBtn} disabled={pos === 0} onClick={() => go(pos - 1)}>&larr; Back</button>
                <button className={navBtn} onClick={() => go(pos + 1)} title="Move on without logging this lead">Skip &rarr;</button>
              </>
            }
          />
        </>
      )}
    </div>
  )
}
