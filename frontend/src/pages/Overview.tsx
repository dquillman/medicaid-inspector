import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import StateHeatmap from '../components/StateHeatmap'
import { SkeletonKPI, SkeletonChart } from '../components/Skeleton'
import type { PrescanStatus } from '../lib/types'

const SIGNAL_LABELS: Record<string, string> = {
  billing_concentration:    'Billing Concentration',
  revenue_per_bene_outlier: 'Revenue Outlier',
  claims_per_bene_anomaly:  'Claims Anomaly',
  billing_ramp_rate:        'Billing Ramp',
  bust_out_pattern:         'Bust-Out',
  ghost_billing:            'Ghost Billing',
  total_spend_outlier:      'Total Spend Outlier',
  billing_consistency:      'Billing Consistency',
  bene_concentration:       'Bene Concentration',
  upcoding_pattern:         'Upcoding',
  address_cluster_risk:     'Address Cluster',
  oig_excluded:             'OIG Exclusion',
  specialty_mismatch:       'Specialty Mismatch',
  corporate_shell_risk:     'Corporate Shell',
  dead_npi_billing:         'Dead NPI Billing',
  new_provider_explosion:   'New Provider Explosion',
  geographic_impossibility: 'Geographic Impossibility',
}

export default function Overview() {
  const navigate = useNavigate()

  // Adaptive polling: poll fast (5s) during active scan, slow (30s) when idle
  const { data: scanStatus } = useQuery<PrescanStatus>({
    queryKey: ['prescan-status'],
    queryFn: api.prescanStatus,
    refetchInterval: (query) => (query.state.data?.phase ?? 0) > 0 ? 5000 : 30000,
  })
  const isScanActive = (scanStatus?.phase ?? 0) > 0
  const pollInterval = isScanActive ? 5000 : 60000

  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ['summary'],
    queryFn: api.summary,
    refetchInterval: pollInterval,
  })

  const { data: signals } = useQuery({
    queryKey: ['signal-summary'],
    queryFn: api.signalSummary,
    refetchInterval: pollInterval,
  })

  const { data: heatmap } = useQuery({
    queryKey: ['state-heatmap'],
    queryFn: api.stateHeatmap,
    refetchInterval: pollInterval,
  })

  const { data: reviewCounts } = useQuery({
    queryKey: ['review-counts'],
    queryFn: api.reviewCounts,
    refetchInterval: pollInterval,
  })

  const { data: moversData } = useQuery({
    queryKey: ['score-movers'],
    queryFn: () => api.scoreMovers(5),
    refetchInterval: pollInterval,
  })

  const confirmedFraud = reviewCounts?.confirmed_fraud ?? 0

  const barData = (signals ?? []).map(s => ({
    signal: s.signal,
    name: SIGNAL_LABELS[s.signal] ?? s.signal,
    count: s.count,
  }))
  const barHeight = Math.max(400, barData.length * 32)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white uppercase tracking-wide flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" className="w-6 h-6 shrink-0">
            <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
            <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" strokeWidth="1.5"/>
            <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" strokeWidth="4"/>
            <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
            <text x="28" y="33" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="11" fill="#f59e0b">$</text>
            <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" strokeWidth="4.5" strokeLinecap="round"/>
            <circle cx="46" cy="18" r="6" fill="#ef4444"/>
            <text x="46" y="22" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="9" fill="white">!</text>
          </svg>
          Threat Dashboard
        </h1>
        <p className="text-gray-500 text-xs mt-1 uppercase tracking-wider">
          Medicaid Provider-Level Claims Analysis · 2018--2024 · 220M+ Records
        </p>
      </div>

      {/* Threat-level KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {sumLoading ? (
          <>
            <SkeletonKPI />
            <SkeletonKPI />
            <SkeletonKPI />
          </>
        ) : (
          <>
            {/* Confirmed Fraud — dominant dark red panel */}
            <div
              className="bg-red-950 border-2 border-red-700 rounded-xl p-5 text-center cursor-pointer hover:border-red-500 transition-colors"
              style={{ animation: confirmedFraud > 0 ? 'threat-pulse-bg 3s ease-in-out infinite' : undefined }}
              onClick={() => navigate('/review?status=confirmed_fraud')}
            >
              <p className="text-red-500 text-xs font-bold uppercase tracking-widest mb-2">CONFIRMED FRAUD CASES</p>
              <p className="text-5xl font-black text-red-400">
                {confirmedFraud.toLocaleString()}
              </p>
              <p className="text-red-700 text-xs mt-2 uppercase tracking-wider">Requires Immediate Action</p>
            </div>

            {/* High Risk — alarming */}
            <div
              className="bg-red-950/40 border-2 border-red-800/60 rounded-xl p-5 text-center cursor-pointer hover:border-red-500 transition-colors"
              onClick={() => navigate('/providers?risk_min=50')}
            >
              <p className="text-red-400 text-xs font-bold uppercase tracking-widest mb-2">HIGH RISK PROVIDERS</p>
              <p className="text-5xl font-black text-red-400">
                {(summary?.high_risk_providers ?? 0).toLocaleString()}
              </p>
              <p className="text-red-800 text-xs mt-2 uppercase tracking-wider">Score &ge; 50</p>
            </div>

            {/* Flagged for Review — warning */}
            <div
              className="bg-yellow-950/30 border-2 border-yellow-800/50 rounded-xl p-5 text-center cursor-pointer hover:border-yellow-500 transition-colors"
              onClick={() => navigate('/providers?risk_min=10.1')}
            >
              <p className="text-yellow-500 text-xs font-bold uppercase tracking-widest mb-2">FLAGGED FOR REVIEW</p>
              <p className="text-4xl font-extrabold text-yellow-400">
                {(summary?.flagged_providers ?? 0).toLocaleString()}
              </p>
              <p className="text-yellow-800 text-xs mt-2 uppercase tracking-wider">Score &gt; 10</p>
            </div>
          </>
        )}
      </div>

      {/* Secondary KPI row — de-emphasized */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {sumLoading ? (
          <>
            <SkeletonKPI />
            <SkeletonKPI />
            <SkeletonKPI />
            <SkeletonKPI />
          </>
        ) : (
          <>
            <div className="card py-3">
              <p className="text-gray-600 text-xs uppercase tracking-wider">Total Spend</p>
              <p className="text-2xl font-bold mt-1 text-blue-400">
                {summary ? fmt(summary.total_paid) : '---'}
              </p>
            </div>
            <div className="card py-3">
              <p className="text-gray-600 text-xs uppercase tracking-wider">Providers Scanned</p>
              <p className="text-2xl font-bold mt-1 text-purple-400">
                {summary ? summary.total_providers.toLocaleString() : '---'}
              </p>
            </div>
            <div className="card py-3">
              <p className="text-gray-600 text-xs uppercase tracking-wider">Total Claims</p>
              <p className="text-2xl font-bold mt-1 text-gray-400">
                {summary ? summary.total_claims.toLocaleString() : '---'}
              </p>
            </div>
            <div className="card py-3">
              <p className="text-gray-600 text-xs uppercase tracking-wider">Avg Risk Score</p>
              <p className="text-2xl font-bold mt-1 text-gray-400">
                {summary ? summary.avg_risk_score.toFixed(1) : '---'}
              </p>
            </div>
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* State heatmap */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Flagged Providers by State</h2>
          <div className="h-[28rem]">
            {heatmap ? (
              <StateHeatmap data={heatmap.by_state} onStateClick={(st) => navigate(`/providers?state=${st}`)} />
            ) : (
              <SkeletonChart />
            )}
          </div>
          <p className="text-xs text-gray-600 mt-2">Color intensity = flagged provider count. State data from NPPES.</p>
        </div>

        {/* Fraud signals bar chart */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Top Fraud Signals (provider count)</h2>
          {barData.length > 0 ? (
            <ResponsiveContainer width="100%" height={barHeight}>
              <BarChart data={barData} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} />
                <YAxis
                  type="category" dataKey="name" width={180}
                  tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} axisLine={false}
                />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                  formatter={(v: number) => [v.toLocaleString(), 'Providers']}
                />
                <Bar
                  dataKey="count"
                  fill="#ef4444"
                  radius={[0, 4, 4, 0]}
                  cursor="pointer"
                  onClick={(_data: any, index: number) => {
                    const sig = barData[index]?.signal
                    if (sig) navigate(`/anomalies?signal=${sig}`)
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-600 text-sm">
              Scan some providers to see fraud signals…
            </div>
          )}
        </div>
      </div>

      {/* Biggest Score Movers */}
      {moversData && (moversData.rising.length > 0 || moversData.falling.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Rising Risk */}
          <div className="card border-red-900/40">
            <h2 className="text-sm font-semibold text-red-400 mb-3 flex items-center gap-2">
              <span className="text-lg">{'\u2191'}</span> Rising Risk Scores
            </h2>
            {moversData.rising.length > 0 ? (
              <div className="space-y-2">
                {moversData.rising.map((m: any) => (
                  <div
                    key={m.npi}
                    className="flex items-center justify-between px-3 py-2 bg-red-950/30 border border-red-900/30 rounded-lg cursor-pointer hover:border-red-700 transition-colors"
                    onClick={() => navigate(`/providers/${m.npi}`)}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-200 truncate">{m.provider_name || m.npi}</p>
                      <p className="text-xs text-gray-500 font-mono">{m.npi}</p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 ml-3">
                      <span className="text-xs text-gray-500">{m.previous_score.toFixed(0)}</span>
                      <span className="text-red-400 text-xs font-bold">{'\u2192'}</span>
                      <span className={`text-sm font-bold ${m.current_score >= 50 ? 'text-red-400' : 'text-yellow-400'}`}>
                        {m.current_score.toFixed(0)}
                      </span>
                      <span className="text-xs font-bold text-red-400 bg-red-950 px-1.5 py-0.5 rounded">
                        +{m.delta.toFixed(1)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-600">No rising scores detected.</p>
            )}
          </div>

          {/* Falling Risk */}
          <div className="card border-green-900/40">
            <h2 className="text-sm font-semibold text-green-400 mb-3 flex items-center gap-2">
              <span className="text-lg">{'\u2193'}</span> Falling Risk Scores
            </h2>
            {moversData.falling.length > 0 ? (
              <div className="space-y-2">
                {moversData.falling.map((m: any) => (
                  <div
                    key={m.npi}
                    className="flex items-center justify-between px-3 py-2 bg-green-950/30 border border-green-900/30 rounded-lg cursor-pointer hover:border-green-700 transition-colors"
                    onClick={() => navigate(`/providers/${m.npi}`)}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-200 truncate">{m.provider_name || m.npi}</p>
                      <p className="text-xs text-gray-500 font-mono">{m.npi}</p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 ml-3">
                      <span className="text-xs text-gray-500">{m.previous_score.toFixed(0)}</span>
                      <span className="text-green-400 text-xs font-bold">{'\u2192'}</span>
                      <span className="text-sm font-bold text-green-400">
                        {m.current_score.toFixed(0)}
                      </span>
                      <span className="text-xs font-bold text-green-400 bg-green-950 px-1.5 py-0.5 rounded">
                        {m.delta.toFixed(1)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-600">No falling scores detected.</p>
            )}
          </div>
        </div>
      )}

    </div>
  )
}
