import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import RiskScoreBadge from '../components/RiskScoreBadge'

const SIGNALS = [
  { key: '', label: 'All' },
  { key: 'billing_ramp_rate',        label: 'Ramp Rate' },
  { key: 'billing_concentration',    label: 'Concentration' },
  { key: 'revenue_per_bene_outlier', label: 'Revenue Outlier' },
  { key: 'bust_out_pattern',         label: 'Bust-Out' },
  { key: 'ghost_billing',            label: 'Ghost Billing' },
  { key: 'claims_per_bene_anomaly',  label: 'Claims Anomaly' },
]

function fmt(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v}`
}

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
  const [activeSignal, setActiveSignal] = useState('')
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

      {/* Signal tabs */}
      <div className="flex gap-1 border-b border-gray-800 pb-0">
        {SIGNALS.map(s => (
          <button
            key={s.key}
            onClick={() => { setActiveSignal(s.key); setPage(1) }}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeSignal === s.key
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {s.label}
          </button>
        ))}
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
