import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { threatColor } from '../lib/threat'
import Breadcrumbs from '../components/Breadcrumbs'
import ProviderFlags from '../components/ProviderFlags'

const KIND_ORDER = ['active_exclusion', 'deactivated_billing', 'deactivated_window', 'recovery_lead'] as const

/** Per-se kinds are not equally damning — colour them by how provable they are. */
const KIND_STYLE: Record<string, string> = {
  active_exclusion:    'bg-red-950/60 border-red-800 text-red-300',
  deactivated_billing: 'bg-orange-950/60 border-orange-800 text-orange-300',
  deactivated_window:  'bg-amber-950/60 border-amber-800 text-amber-300',
  recovery_lead:       'bg-slate-800/60 border-slate-700 text-slate-300',
}

export default function Excluded() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['excluded-providers'],
    queryFn: () => api.excludedProviders(),
    staleTime: 10 * 60_000,
  })

  const [kind, setKind] = useState<string | null>(null)
  const [onlyUnseen, setOnlyUnseen] = useState(false)

  const labels = data?.kind_labels ?? {}
  const rows = useMemo(() => {
    let r = data?.providers ?? []
    if (kind) r = r.filter(p => p.kind === kind)
    if (onlyUnseen) r = r.filter(p => p.in_scan_cache === false)
    return r
  }, [data, kind, onlyUnseen])

  const unseenTotal = useMemo(
    () => (data?.providers ?? []).filter(p => p.in_scan_cache === false).length,
    [data],
  )

  const kindsPresent = useMemo(() => {
    const seen = new Set((data?.providers ?? []).map(p => p.kind).filter(Boolean))
    return KIND_ORDER.filter(k => seen.has(k))
  }, [data])

  return (
    <div className="space-y-5">
      <Breadcrumbs />

      <div>
        <h1 className="text-xl font-bold text-gray-200">Barred From Billing — And Billed Anyway</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-3xl">
          Providers on the federal OIG LEIE exclusion list, and NPIs CMS deactivated, that
          still drew Medicaid payments. These are per-se findings: no statistical inference,
          no peer comparison — a barred party was paid. They are removed from the Providers
          list, Anomalies, Review Queue, and Fraud Brain, so this page is their single home.
        </p>
        {data?.universe_note && (
          <p className="text-xs text-filament-core mt-2 max-w-3xl">{data.universe_note}</p>
        )}
      </div>

      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 max-w-3xl">
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Barred &amp; Billing</p>
            <p className="text-xl font-bold text-red-400">{data.total.toLocaleString()}</p>
          </div>
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Total Paid</p>
            <p className="text-xl font-bold text-red-400">{fmt(data.total_paid)}</p>
          </div>
          {unseenTotal > 0 && (
            <div className="card py-3 border-filament-core/40">
              <p className="text-[10px] text-gray-600 uppercase tracking-wider">Below the Scan Cutoff</p>
              <p className="text-xl font-bold text-filament-core">{unseenTotal.toLocaleString()}</p>
              <p className="text-[10px] text-gray-600 mt-0.5">invisible to the risk model</p>
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      {data && kindsPresent.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setKind(null)}
            className={`text-xs px-2.5 py-1 rounded border transition-colors ${
              kind === null ? 'bg-gray-700 border-gray-600 text-gray-100' : 'border-gray-800 text-gray-500 hover:text-gray-300'
            }`}
          >
            All ({data.total.toLocaleString()})
          </button>
          {kindsPresent.map(k => {
            const n = data.by_kind?.[k]?.count ?? 0
            return (
              <button
                key={k}
                onClick={() => setKind(kind === k ? null : k)}
                className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                  kind === k ? KIND_STYLE[k] : 'border-gray-800 text-gray-500 hover:text-gray-300'
                }`}
              >
                {labels[k] ?? k} ({n.toLocaleString()})
              </button>
            )
          })}
          {unseenTotal > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-gray-500 ml-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={onlyUnseen}
                onChange={e => setOnlyUnseen(e.target.checked)}
                className="accent-filament-core"
              />
              Only leads the risk model can&apos;t see
            </label>
          )}
        </div>
      )}

      {isLoading && (
        <div className="card h-32 flex items-center justify-center text-gray-600 text-sm">
          Cross-referencing OIG LEIE and NPI deactivations…
        </div>
      )}
      {error != null && (
        <div className="card border-red-900/60">
          <p className="text-sm text-red-400">Failed to load: {String(error)}</p>
        </div>
      )}

      {data && rows.length === 0 && (
        <div className="card">
          <p className="text-sm text-gray-500">
            {data.total === 0
              ? 'No providers matched the OIG exclusion list or the deactivated-NPI list.'
              : 'No leads match these filters.'}
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] text-gray-600 uppercase tracking-wider border-b border-gray-800">
                <th className="py-2 pr-4">NPI</th>
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">State</th>
                <th className="py-2 pr-4">Finding</th>
                <th className="py-2 pr-4">Barred Since</th>
                <th className="py-2 pr-4 text-right">Paid While Barred</th>
                <th className="py-2 pr-4 text-right">Total Paid</th>
                <th className="py-2 text-right">Risk</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(p => {
                const barred = p.paid_after_exclusion ?? p.paid_after_deactivation ?? p.paid_during_deactivation
                const since = p.exclusion_date || p.deactivation_date || p.excl_date
                return (
                  <tr
                    key={p.npi}
                    className="border-b border-gray-900 hover:bg-gray-900/40"
                    style={{ borderLeft: `3px solid ${threatColor(p.risk_score)}` }}
                  >
                    <td className="py-2 pr-4 font-mono text-xs">
                      <Link to={`/providers/${p.npi}`} className="text-blue-400 hover:underline">{p.npi}</Link>
                      {p.in_scan_cache === false && (
                        <span
                          className="ml-1.5 text-[9px] px-1 py-0.5 rounded border border-filament-core/40 text-filament-core align-middle"
                          title="Below the $1M scan cutoff — this provider is not in the risk model at all"
                        >
                          UNSCANNED
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-gray-300">
                      {p.provider_name || '—'}
                      <ProviderFlags npi={p.npi} className="ml-1.5" />
                    </td>
                    <td className="py-2 pr-4 text-gray-400">{p.state || '—'}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-[10px] px-2 py-0.5 border rounded ${KIND_STYLE[p.kind ?? ''] ?? 'border-gray-800 text-gray-500'}`}>
                        {labels[p.kind ?? ''] ?? p.excl_type ?? '—'}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-gray-400 font-mono text-xs">{since || '—'}</td>
                    <td className="py-2 pr-4 text-right font-mono text-red-400">
                      {barred ? fmt(barred) : <span className="text-gray-700">—</span>}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-gray-300">{fmt(p.total_paid)}</td>
                    <td className="py-2 text-right font-mono text-gray-400">
                      {p.risk_score ? p.risk_score : <span className="text-gray-700">n/a</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {data?.generated_at && (
        <p className="text-[11px] text-gray-600">
          Sweep built {data.generated_at}. Rebuild with{' '}
          <code className="font-mono text-gray-500">scripts/build_perse_sweep.py</code> after an OIG or NPPES refresh.
        </p>
      )}
    </div>
  )
}
