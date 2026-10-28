import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import Breadcrumbs from '../components/Breadcrumbs'
import ProviderFlags from '../components/ProviderFlags'
import type { DojShortlistLead } from '../lib/types'
import { DOJ_TIERS as TIERS } from '../lib/dojTiers'

export default function DojShortlist() {
  const [includeOlder, setIncludeOlder] = useState(false)
  const { data, isLoading, error } = useQuery({
    queryKey: ['doj-shortlist', includeOlder],
    queryFn: () => api.dojShortlist(includeOlder),
    // Coming back from filing must show the list at once (kept 30 min) and
    // refresh quietly behind it, so the lead just filed drops off.
    staleTime: 30_000,
    gcTime: 30 * 60_000,
    refetchOnWindowFocus: true,
  })
  const [tier, setTier] = useState<1 | 2 | 3 | null>(null)
  const [priorityOnly, setPriorityOnly] = useState(false)

  const rows = useMemo(() => {
    let r: DojShortlistLead[] = data?.leads ?? []
    if (tier) r = r.filter(l => l.tier === tier)
    if (priorityOnly) r = r.filter(l => l.doj_priority_area)
    return r
  }, [data, tier, priorityOnly])

  return (
    <div className="space-y-5">
      <Breadcrumbs />

      <div>
        <h1 className="text-xl font-bold text-gray-200">DOJ Shortlist</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-3xl">
          Leads ranked for investigator review. Administrative discrepancies and statistical anomalies require verification. DOJ pays
          ($10,000&ndash;$30,000 per distinct tip, at its discretion) only when a tip leads to criminal
          charges, and eligibility is determined by DOJ. Hospice, home health, day care and
          special services rank first inside each group, because DOJ names them as priorities.
        </p>
        {data && (
          <p className="text-xs text-gray-500 mt-2 max-w-3xl">
            Left off: {data.dropped.too_old.toLocaleString()} last billed before {data.cutoff_month}{' '}
            (age prioritization only; this does not determine legal eligibility) &middot;{' '}
            {data.dropped.already_doj.toLocaleString()} already filed with DOJ (any NPI of the company) &middot;{' '}
            {data.dropped.closed.toLocaleString()} dismissed or archived
            {data.dropped.same_company ? <> &middot; {data.dropped.same_company.toLocaleString()} extra NPIs merged into their company&rsquo;s row</> : null}
            {data.dropped.short_lapse ? <> &middot; {data.dropped.short_lapse.toLocaleString()} short NPI lapses (deactivated under 6 months, then reactivated: usually paperwork)</> : null}.
          </p>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-300">
        <input type="checkbox" checked={includeOlder} onChange={e => setIncludeOlder(e.target.checked)} />
        Include older evidence for timeliness review
      </label>
      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-4xl">
          {TIERS.map(t => (
            <button
              key={t.tier}
              onClick={() => setTier(tier === t.tier ? null : t.tier)}
              className={`card py-3 text-left transition-colors ${tier === t.tier ? 'border-amber-500/60' : 'hover:border-gray-600'}`}
            >
              <p className="text-[10px] text-gray-500 uppercase tracking-wider">{t.tier}. {t.label}</p>
              <p className="text-xl font-bold text-gray-100">{(data.by_tier[String(t.tier) as '1' | '2' | '3'] ?? 0).toLocaleString()}</p>
              <p className="text-[10px] text-gray-500 mt-0.5 leading-snug">{t.blurb}</p>
            </button>
          ))}
        </div>
      )}

      {data && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer select-none">
            <input type="checkbox" checked={priorityOnly} onChange={e => setPriorityOnly(e.target.checked)} className="accent-amber-500" />
            Only DOJ priority areas (hospice, home health, day care, special services)
          </label>
          <Link
            to={`/doj-filing?${new URLSearchParams({ ...(tier ? { tier: String(tier) } : {}), ...(priorityOnly ? { priority: '1' } : {}) })}`}
            className="px-4 py-2 text-sm font-semibold rounded bg-amber-600 hover:bg-amber-500 text-black"
            title="Walk these leads one at a time, with each report ready"
          >
            Start filing ({rows.length.toLocaleString()}) &rarr;
          </Link>
        </div>
      )}

      {isLoading && (
        <div className="card h-32 flex items-center justify-center text-gray-600 text-sm">Building the DOJ shortlist…</div>
      )}
      {error != null && (
        <div className="card border-red-900/60"><p className="text-sm text-red-400">Failed to load: {String(error)}</p></div>
      )}
      {data && rows.length === 0 && (
        <div className="card"><p className="text-sm text-gray-500">No leads match these filters.</p></div>
      )}

      {rows.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] text-gray-600 uppercase tracking-wider border-b border-gray-800">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Provider</th>
                <th className="py-2 pr-3">State</th>
                <th className="py-2 pr-3">Why it is on the list</th>
                <th className="py-2 pr-3 text-right">Dollars</th>
                <th className="py-2 pr-3">Last billed</th>
                <th className="py-2 text-right">File</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(l => {
                const t = TIERS[l.tier - 1]
                return (
                  <tr key={l.npi} className="border-b border-gray-900 hover:bg-gray-900/40 align-top">
                    <td className="py-2 pr-3 font-mono text-xs text-gray-500">{l.rank}</td>
                    <td className="py-2 pr-3">
                      <Link to={`/providers/${l.npi}`} className="text-blue-400 hover:underline">{l.provider_name || l.npi}</Link>
                      <ProviderFlags npi={l.npi} className="ml-1.5" />
                      <p className="text-[10px] text-gray-600 font-mono">{l.npi} &middot; {l.specialty || 'specialty unknown'}</p>
                      {l.related_npis && l.related_npis.length > 0 && (
                        <p className="text-[10px] text-amber-400/80 font-mono" title="Same company. File it as ONE tip and list all of these NPIs in it.">
                          +{l.related_npis.length} more NPI{l.related_npis.length === 1 ? '' : 's'}: {l.related_npis.join(', ')}
                        </p>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-gray-400">{l.state || '—'}</td>
                    <td className="py-2 pr-3">
                      <span className={`text-[10px] px-2 py-0.5 border rounded ${t.style}`}>{t.label}</span>
                      {l.doj_priority_area && (
                        <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded border border-amber-400/60 bg-amber-400/10 text-amber-300">
                          DOJ priority &middot; {l.doj_priority_area}
                        </span>
                      )}
                      <p className="text-xs text-gray-300 mt-1">{l.reason}</p>
                      {l.caveat && <p className="text-[10px] text-amber-400 mt-0.5">CHECK FIRST: {l.caveat}</p>}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      <p className="font-mono text-red-400">{fmt(l.amount)}</p>
                      <p className="text-[10px] text-gray-600">{l.amount_label}</p>
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs text-gray-400">{l.last_month || '—'}</td>
                    <td className="py-2 text-right">
                      <Link
                        to={`/providers/${l.npi}/doj-referral`}
                        className="inline-block px-2.5 py-1 text-[11px] font-semibold rounded border border-amber-400 text-amber-200 bg-amber-500/15 hover:bg-amber-500/25"
                      >
                        DOJ Tip
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
