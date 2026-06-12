import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import Breadcrumbs from '../components/Breadcrumbs'
import type { FraudBrainProvider } from '../lib/types'

const COMPONENT_LABELS: Record<string, string> = {
  rule_signals: '18 Fraud Signals',
  ml_anomaly: 'ML Anomaly',
  corroboration: 'Claim-Level Analyses',
  dollars: 'Dollars at Risk',
  flag_breadth: 'Signal Breadth',
}

function scoreColor(score: number) {
  if (score >= 75) return 'text-red-400'
  if (score >= 55) return 'text-orange-400'
  if (score >= 35) return 'text-yellow-400'
  return 'text-blue-400'
}

function RankCard({ rank, p }: { rank: number; p: FraudBrainProvider }) {
  const [expanded, setExpanded] = useState(rank <= 3)
  const maxComponent = Math.max(...Object.values(p.components), 1)

  return (
    <div className={`card ${p.brain_score >= 75 ? 'border-red-900/60' : ''}`}>
      <div className="flex items-start gap-4">
        <div className="text-3xl font-bold text-gray-700 w-12 text-center shrink-0">#{rank}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-3 flex-wrap">
            <Link to={`/providers/${p.npi}`} className="text-base font-semibold text-blue-400 hover:underline truncate">
              {p.provider_name || p.npi}
            </Link>
            <span className="font-mono text-xs text-gray-500">{p.npi}</span>
            {p.state && <span className="text-xs px-2 py-0.5 bg-gray-800 border border-gray-700 rounded text-gray-400">{p.state}</span>}
            {p.oig_excluded && (
              <span className="text-xs px-2 py-0.5 bg-red-900 border border-red-700 rounded-full text-red-300 font-bold">
                OIG EXCLUDED
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{p.specialty || '—'}</p>

          <div className="flex items-center gap-6 mt-3">
            <div>
              <p className="text-[10px] text-gray-600 uppercase tracking-wider">Brain Score</p>
              <p className={`text-2xl font-bold ${scoreColor(p.brain_score)}`}>{p.brain_score.toFixed(1)}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-600 uppercase tracking-wider">Total Paid</p>
              <p className="text-lg font-semibold text-gray-300">{fmt(p.total_paid)}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-600 uppercase tracking-wider">Signals Fired</p>
              <p className="text-lg font-semibold text-gray-300">{p.flag_count}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-600 uppercase tracking-wider">Corroborating Analyses</p>
              <p className="text-lg font-semibold text-gray-300">{p.corroborating_sources}</p>
            </div>
          </div>

          {/* Component bars */}
          <div className="mt-3 space-y-1">
            {Object.entries(p.components).map(([key, value]) => (
              <div key={key} className="flex items-center gap-2">
                <span className="text-[10px] text-gray-500 w-36 shrink-0">{COMPONENT_LABELS[key] ?? key}</span>
                <div className="flex-1 h-1.5 bg-gray-800 rounded overflow-hidden">
                  <div
                    className="h-full bg-blue-600 rounded"
                    style={{ width: `${Math.min((value / maxComponent) * 100, 100)}%` }}
                  />
                </div>
                <span className="text-[10px] font-mono text-gray-500 w-8 text-right">{value.toFixed(1)}</span>
              </div>
            ))}
          </div>

          {/* Evidence */}
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-3 text-xs text-blue-500 hover:text-blue-400"
          >
            {expanded ? '▾ Hide' : '▸ Show'} evidence ({p.evidence.length})
          </button>
          {expanded && (
            <ul className="mt-2 space-y-1.5">
              {p.evidence.map((e, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span className="font-mono text-gray-600 w-10 text-right shrink-0">+{e.points.toFixed(1)}</span>
                  <div>
                    <span className="text-gray-400 font-medium">{e.source}:</span>{' '}
                    <span className="text-gray-500">{e.detail}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

export default function FraudBrain() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['fraud-brain'],
    queryFn: () => api.fraudBrainTop(10),
    staleTime: 5 * 60_000,
  })

  return (
    <div className="space-y-5">
      <Breadcrumbs />

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-200">Fraud Brain</h1>
          <p className="text-sm text-gray-500 mt-1 max-w-3xl">
            Cross-source meta-analysis: fuses the 18 rule-based signals, ML anomaly detection,
            claim-level pattern analyses (unbundling, duplicates, impossible volume), pharmacy/DME
            findings, doctor-shopping overlap, diagnosis mismatches, and financial exposure into
            one ranked list of the most probable frauds. OIG-excluded providers are omitted —
            they're already barred and live on the Excluded page.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="shrink-0 px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded text-gray-300 disabled:opacity-50"
        >
          {isFetching ? 'Computing…' : 'Recompute'}
        </button>
      </div>

      {data && (
        <div className="grid grid-cols-4 gap-4">
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Providers Evaluated</p>
            <p className="text-xl font-bold text-gray-200">{data.providers_evaluated.toLocaleString()}</p>
          </div>
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">ML Model</p>
            <p className={`text-xl font-bold ${data.ml_model_used ? 'text-green-400' : 'text-gray-500'}`}>
              {data.ml_model_used ? 'Active' : 'Untrained'}
            </p>
          </div>
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Corroborated Providers</p>
            <p className="text-xl font-bold text-gray-200">{data.corroborated_providers.toLocaleString()}</p>
          </div>
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Computed In</p>
            <p className="text-xl font-bold text-gray-200">
              {data.cached ? 'cached' : `${(data.computed_in_ms / 1000).toFixed(1)}s`}
            </p>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="card h-40 flex items-center justify-center text-gray-600 text-sm">
          Scoring all providers across every data source…
        </div>
      )}
      {error != null && (
        <div className="card border-red-900/60">
          <p className="text-sm text-red-400">Fraud Brain failed: {String(error)}</p>
        </div>
      )}
      {data?.note && <div className="card"><p className="text-sm text-gray-500">{data.note}</p></div>}

      <div className="space-y-4">
        {data?.top.map((p, i) => <RankCard key={p.npi} rank={i + 1} p={p} />)}
      </div>
    </div>
  )
}
