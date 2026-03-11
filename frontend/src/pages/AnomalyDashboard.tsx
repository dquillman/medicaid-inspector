import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import RiskScoreBadge from '../components/RiskScoreBadge'
import { fmt } from '../lib/format'

const SIGNALS = [
  { key: '',                          label: 'All' },
  { key: 'billing_concentration',     label: 'Billing Concentration' },
  { key: 'revenue_per_bene_outlier',  label: 'Revenue Outlier' },
  { key: 'claims_per_bene_anomaly',   label: 'Claims Anomaly' },
  { key: 'billing_ramp_rate',         label: 'Ramp Rate' },
  { key: 'bust_out_pattern',          label: 'Bust-Out' },
  { key: 'ghost_billing',             label: 'Ghost Billing' },
  { key: 'total_spend_outlier',       label: 'Total Spend Outlier' },
  { key: 'billing_consistency',       label: 'Billing Consistency' },
  { key: 'bene_concentration',        label: 'Bene Concentration' },
  { key: 'upcoding_pattern',          label: 'Upcoding Pattern' },
  { key: 'address_cluster_risk',      label: 'Address Cluster' },
  { key: 'oig_excluded',              label: 'OIG Exclusion' },
  { key: 'specialty_mismatch',        label: 'Specialty Mismatch' },
  { key: 'corporate_shell_risk',      label: 'Corporate Shell' },
  { key: 'dead_npi_billing',          label: 'Dead NPI Billing' },
  { key: 'new_provider_explosion',    label: 'New Provider Explosion' },
  { key: 'geographic_impossibility',  label: 'Geographic Impossibility' },
]

function exportCsv(rows: any[]) {
  if (!rows.length) return
  const headers = ['npi', 'risk_score', 'total_paid', 'total_claims', 'flags']
  const lines = [
    headers.join(','),
    ...rows.map(r => [
      r.npi,
      r.risk_score,
      r.total_paid,
      r.total_claims,
      r.flags?.map((f: any) => f.signal).join('|') ?? '',
    ].join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'medicaid-anomalies.csv'
  a.click()
}

export default function AnomalyDashboard() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const signalParam = searchParams.get('signal') ?? ''
  const [activeSignal, setActiveSignal] = useState(signalParam)
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: ['anomalies', activeSignal, page],
    queryFn: () => api.anomalies({ signal: activeSignal, page, limit: 50 }),
  })

  const anomalies = data?.anomalies ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Anomaly Dashboard</h1>
          <p className="text-gray-400 text-sm mt-1">
            Providers with risk score &gt; 60 · {data?.total ?? '…'} total
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => exportCsv(anomalies)}
          disabled={anomalies.length === 0}
        >
          Export CSV
        </button>
      </div>

      {/* Summary stats */}
      {data && !isLoading && (
        <div className="card py-3 px-5 flex items-center gap-6">
          <span className="text-sm text-gray-300">
            <span className="text-white font-bold">{data.total?.toLocaleString() ?? 0}</span> providers flagged
          </span>
          <span className="text-gray-700">|</span>
          <span className="text-sm text-gray-300">
            across <span className="text-white font-bold">{SIGNALS.length - 1}</span> unique signals
          </span>
        </div>
      )}

      {/* Signal filters */}
      <div className="card p-3">
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2 font-medium">Filter by Signal</p>
        <div className="flex flex-wrap gap-1.5">
          {SIGNALS.map(s => (
            <button
              key={s.key}
              onClick={() => { setActiveSignal(s.key); setPage(1) }}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                activeSignal === s.key
                  ? 'bg-blue-600 text-white shadow-sm shadow-blue-900/40'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/80">
              {['NPI','Risk Score','Total Paid','Claims','Active Months','Active Flags'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  Loading from prescan cache…
                </td>
              </tr>
            )}
            {anomalies.map(p => (
              <tr
                key={p.npi}
                className="hover:bg-gray-800/50 cursor-pointer transition-colors"
                onClick={() => navigate(`/providers/${p.npi}`)}
              >
                <td className="px-4 py-3 font-mono text-blue-400 text-xs">{p.npi}</td>
                <td className="px-4 py-3">
                  <RiskScoreBadge score={p.risk_score} size="sm" />
                </td>
                <td className="px-4 py-3 font-semibold">{fmt(p.total_paid)}</td>
                <td className="px-4 py-3 text-gray-400">{p.total_claims?.toLocaleString()}</td>
                <td className="px-4 py-3 text-gray-400">{p.active_months}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {p.flags?.map(f => (
                      <span key={f.signal} className="badge-high text-xs">{f.signal.replace(/_/g, ' ')}</span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {!isLoading && anomalies.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No anomalies found. Prescan may still be running — check back in a minute.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center gap-3 justify-end">
        <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
        <span className="text-gray-500 text-sm">Page {page}</span>
        <button className="btn-ghost" disabled={anomalies.length < 50} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>
    </div>
  )
}
