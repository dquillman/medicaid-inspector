import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { api, type HotspotArea, type HotspotAreaDetail } from '../lib/api'

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: '#ef4444',
  HIGH:     '#f97316',
  ELEVATED: '#eab308',
  NORMAL:   '#22c55e',
}

const SEVERITY_BG: Record<string, string> = {
  CRITICAL: 'bg-red-900/40 text-red-300 border-red-700',
  HIGH:     'bg-orange-900/40 text-orange-300 border-orange-700',
  ELEVATED: 'bg-yellow-900/40 text-yellow-300 border-yellow-700',
  NORMAL:   'bg-green-900/40 text-green-300 border-green-700',
}

const FILTERS = ['All', 'CRITICAL', 'HIGH', 'ELEVATED'] as const

function fmt$(n: number) {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

export default function FraudHotspots() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<string>('All')
  const [expandedZip, setExpandedZip] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['hotspots-composite'],
    queryFn: () => api.hotspotsComposite(),
    staleTime: 30_000,
  })

  const { data: detailData } = useQuery({
    queryKey: ['hotspot-detail', expandedZip],
    queryFn: () => api.hotspotZip(expandedZip!),
    enabled: !!expandedZip,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400 animate-pulse">Loading hotspot data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card p-6 text-center">
        <p className="text-red-400">Failed to load hotspot data</p>
        <p className="text-gray-500 text-sm mt-1">{String(error)}</p>
      </div>
    )
  }

  if (!data || data.total_areas === 0) {
    return (
      <div className="card p-6 text-center">
        <p className="text-gray-400">No hotspot data available. Run a scan first to populate provider data.</p>
      </div>
    )
  }

  const { severity_counts, hotspots } = data

  const filtered = filter === 'All'
    ? hotspots
    : hotspots.filter(h => h.severity === filter)

  // Top 15 for the chart
  const chartData = hotspots.slice(0, 15).map(h => ({
    name: `${h.zip3} (${h.states.join(', ')})`,
    zip3: h.zip3,
    score: h.composite_score,
    severity: h.severity,
  }))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Fraud Hotspot Map</h1>
        <p className="text-gray-400 text-sm mt-1">
          County-level composite fraud risk analysis by 3-digit ZIP prefix
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Critical Hotspots"
          value={severity_counts.CRITICAL ?? 0}
          color="text-red-400"
          sub="Score >= 70"
        />
        <KpiCard
          label="High Hotspots"
          value={severity_counts.HIGH ?? 0}
          color="text-orange-400"
          sub="Score 50-70"
        />
        <KpiCard
          label="Elevated Areas"
          value={severity_counts.ELEVATED ?? 0}
          color="text-yellow-400"
          sub="Score 30-50"
        />
        <KpiCard
          label="Total Areas Analyzed"
          value={data.total_areas}
          color="text-blue-400"
          sub={`${hotspots.reduce((s, h) => s + h.provider_count, 0).toLocaleString()} providers`}
        />
      </div>

      {/* Top 15 Chart */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4 uppercase tracking-wider">
          Top 15 Hotspots by Composite Score
        </h2>
        <ResponsiveContainer width="100%" height={380}>
          <BarChart data={chartData} layout="vertical" margin={{ left: 120, right: 20, top: 5, bottom: 5 }}>
            <XAxis type="number" domain={[0, 100]} tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fill: '#d1d5db', fontSize: 11 }}
              width={110}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              labelStyle={{ color: '#f3f4f6' }}
              formatter={(value: number) => [value.toFixed(1), 'Composite Score']}
            />
            <Bar dataKey="score" radius={[0, 4, 4, 0]}>
              {chartData.map((entry, i) => (
                <Cell key={i} fill={SEVERITY_COLORS[entry.severity] || '#6b7280'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Severity Filter */}
      <div className="flex gap-2">
        {FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={
              filter === f
                ? 'btn-primary'
                : 'btn-ghost'
            }
          >
            {f === 'All' ? 'All Areas' : f}
            {f !== 'All' && (
              <span className="ml-1.5 text-xs opacity-70">
                ({severity_counts[f] ?? 0})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Hotspot Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-3 text-left">ZIP3</th>
              <th className="px-4 py-3 text-left">States</th>
              <th className="px-4 py-3 text-left">Cities</th>
              <th className="px-4 py-3 text-right">Composite</th>
              <th className="px-4 py-3 text-center">Severity</th>
              <th className="px-4 py-3 text-right">Providers</th>
              <th className="px-4 py-3 text-right">Flagged %</th>
              <th className="px-4 py-3 text-right">Avg Risk</th>
              <th className="px-4 py-3 text-right">Billing</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(h => (
              <HotspotRow
                key={h.zip3}
                hotspot={h}
                isExpanded={expandedZip === h.zip3}
                detail={expandedZip === h.zip3 ? detailData ?? null : null}
                onToggle={() => setExpandedZip(expandedZip === h.zip3 ? null : h.zip3)}
                onProviderClick={(npi) => navigate(`/providers/${npi}`)}
              />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-gray-500">
                  No hotspots match the selected filter
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ── KPI Card ─────────────────────────────────────────────────────────────── */

function KpiCard({ label, value, color, sub }: { label: string; value: number; color: string; sub: string }) {
  return (
    <div className="card p-4">
      <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value.toLocaleString()}</p>
      <p className="text-xs text-gray-500 mt-1">{sub}</p>
    </div>
  )
}

/* ── Hotspot Table Row ────────────────────────────────────────────────────── */

function HotspotRow({
  hotspot,
  isExpanded,
  detail,
  onToggle,
  onProviderClick,
}: {
  hotspot: HotspotArea
  isExpanded: boolean
  detail: HotspotAreaDetail | null
  onToggle: () => void
  onProviderClick: (npi: string) => void
}) {
  const h = hotspot
  const sevColor = SEVERITY_COLORS[h.severity] || '#6b7280'

  return (
    <>
      <tr
        className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer transition-colors"
        onClick={onToggle}
      >
        <td className="px-4 py-3 font-mono font-bold text-white">
          <span className="mr-1.5 text-gray-500 text-xs">{isExpanded ? '\u25BC' : '\u25B6'}</span>
          {h.zip3}
        </td>
        <td className="px-4 py-3 text-gray-300">{h.states.join(', ') || '---'}</td>
        <td className="px-4 py-3 text-gray-400 text-xs max-w-[200px] truncate">
          {h.cities.slice(0, 3).join(', ')}{h.cities.length > 3 ? ` +${h.cities.length - 3}` : ''}
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex items-center justify-end gap-2">
            <div className="w-16 h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${h.composite_score}%`, backgroundColor: sevColor }}
              />
            </div>
            <span className="font-bold text-white w-10 text-right">{h.composite_score}</span>
          </div>
        </td>
        <td className="px-4 py-3 text-center">
          <span className={`text-xs px-2 py-0.5 rounded border ${SEVERITY_BG[h.severity] || 'bg-gray-800 text-gray-400 border-gray-700'}`}>
            {h.severity}
          </span>
        </td>
        <td className="px-4 py-3 text-right text-gray-300">{h.provider_count}</td>
        <td className="px-4 py-3 text-right text-gray-300">{h.flagged_pct}%</td>
        <td className="px-4 py-3 text-right text-gray-300">{h.avg_risk_score}</td>
        <td className="px-4 py-3 text-right text-gray-300">{fmt$(h.total_billing)}</td>
      </tr>

      {/* Expanded detail */}
      {isExpanded && (
        <tr className="bg-gray-900/50">
          <td colSpan={9} className="px-6 py-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Component Breakdown */}
              <div>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Score Components
                </h3>
                <div className="space-y-2">
                  <ComponentBar label="Avg Risk Score" value={h.components.avg_risk} weight="30%" color="#3b82f6" />
                  <ComponentBar label="Flagged Provider %" value={h.components.flagged_pct} weight="25%" color="#ef4444" />
                  <ComponentBar label="Billing Concentration" value={h.components.billing_concentration} weight="15%" color="#f97316" />
                  <ComponentBar label="Density Anomaly" value={h.components.density_anomaly} weight="15%" color="#a855f7" />
                  <ComponentBar label="High Risk Count" value={h.components.high_risk_count} weight="15%" color="#eab308" />
                </div>
                <div className="mt-3 text-xs text-gray-500 space-y-1">
                  <p>Density ratio: {h.density_ratio}x vs average</p>
                  <p>Top provider billing share: {h.billing_concentration}%</p>
                  <p>High-risk providers (score &gt;= 50): {h.high_risk_count}</p>
                </div>
              </div>

              {/* Top Providers */}
              <div>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Top Providers in Area
                </h3>
                {detail ? (
                  <div className="space-y-1.5">
                    {detail.top_providers.slice(0, 5).map(p => (
                      <div
                        key={p.npi}
                        className="flex items-center gap-3 p-2 rounded bg-gray-800/50 hover:bg-gray-800 cursor-pointer transition-colors"
                        onClick={(e) => { e.stopPropagation(); onProviderClick(p.npi) }}
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-white truncate">{p.provider_name}</p>
                          <p className="text-xs text-gray-500">{p.npi} &middot; {p.state} {p.city}</p>
                        </div>
                        <div className="text-right shrink-0">
                          <p className={`text-sm font-bold ${p.risk_score >= 50 ? 'text-red-400' : p.risk_score > 10 ? 'text-yellow-400' : 'text-green-400'}`}>
                            {p.risk_score}
                          </p>
                          <p className="text-xs text-gray-500">{fmt$(p.total_paid)}</p>
                        </div>
                      </div>
                    ))}
                    {detail.top_providers.length === 0 && (
                      <p className="text-gray-500 text-sm">No providers found</p>
                    )}
                  </div>
                ) : (
                  <div className="text-gray-500 text-sm animate-pulse">Loading providers...</div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

/* ── Component Score Bar ──────────────────────────────────────────────────── */

function ComponentBar({ label, value, weight, color }: { label: string; value: number; weight: string; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-400 w-40 shrink-0">{label} <span className="text-gray-600">({weight})</span></span>
      <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(value, 100)}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-mono text-gray-300 w-8 text-right">{value}</span>
    </div>
  )
}
