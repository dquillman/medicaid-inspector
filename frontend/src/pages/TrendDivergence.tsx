import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Legend, ReferenceLine, Cell,
} from 'recharts'
import { api, TrendState } from '../lib/api'

const fmt = (n: number) =>
  n >= 1_000_000_000 ? `$${(n / 1_000_000_000).toFixed(1)}B`
    : n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M`
      : n >= 1_000 ? `$${(n / 1_000).toFixed(1)}K`
        : `$${n.toFixed(0)}`

function TrendArrow({ direction }: { direction: 'up' | 'down' | 'flat' }) {
  if (direction === 'up') return <span className="text-green-400 font-bold text-lg">&#9650;</span>
  if (direction === 'down') return <span className="text-red-400 font-bold text-lg">&#9660;</span>
  return <span className="text-gray-500 font-bold text-lg">&#9654;</span>
}

function KpiCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card p-4 flex flex-col gap-1">
      <span className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">{label}</span>
      <span className="text-2xl font-bold text-white">{value}</span>
      {sub && <span className="text-xs text-gray-400">{sub}</span>}
    </div>
  )
}

function StateDetailChart({ record }: { record: TrendState }) {
  // Build chart data combining enrollment and billing by year
  const chartData = record.yearly.map(y => {
    const yoy = record.yoy.find(yo => yo.year === y.year)
    return {
      year: y.year,
      enrollment: y.enrollment_millions,
      billing: y.total_billing,
      billingPerEnrollee: y.billing_per_enrollee,
      isDivergent: yoy?.is_divergent ?? false,
      divergencePct: yoy?.divergence_pct ?? 0,
    }
  })

  // YoY chart data
  const yoyData = record.yoy.map(y => ({
    year: y.year,
    enrollment_change: y.enrollment_change_pct,
    billing_change: y.billing_change_pct,
    divergence: y.divergence_pct,
    isDivergent: y.is_divergent,
  }))

  return (
    <div className="space-y-6">
      {/* Dual axis chart: enrollment line + billing bars */}
      <div>
        <h4 className="text-sm font-semibold text-gray-300 mb-3">Enrollment vs Billing Over Time</h4>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="year" stroke="#64748b" fontSize={12} />
            <YAxis
              yAxisId="billing"
              orientation="left"
              stroke="#3b82f6"
              fontSize={11}
              tickFormatter={(v: number) => fmt(v)}
              label={{ value: 'Billing ($)', angle: -90, position: 'insideLeft', fill: '#3b82f6', fontSize: 11 }}
            />
            <YAxis
              yAxisId="enrollment"
              orientation="right"
              stroke="#10b981"
              fontSize={11}
              tickFormatter={(v: number) => `${v}M`}
              label={{ value: 'Enrollment (M)', angle: 90, position: 'insideRight', fill: '#10b981', fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value: number, name: string) => {
                if (name === 'billing') return [fmt(value), 'Billing']
                if (name === 'enrollment') return [`${value}M`, 'Enrollment']
                return [value, name]
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {/* Shade divergent years */}
            {chartData.filter(d => d.isDivergent).map(d => (
              <ReferenceLine
                key={d.year}
                x={d.year}
                yAxisId="billing"
                stroke="#ef444440"
                strokeWidth={40}
                strokeDasharray=""
              />
            ))}
            <Bar yAxisId="billing" dataKey="billing" fill="#3b82f6" opacity={0.7} name="billing" radius={[4, 4, 0, 0]} />
            <Line yAxisId="enrollment" dataKey="enrollment" stroke="#10b981" strokeWidth={3} dot={{ r: 4, fill: '#10b981' }} name="enrollment" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* YoY change chart */}
      <div>
        <h4 className="text-sm font-semibold text-gray-300 mb-3">Year-over-Year Growth Rates (%)</h4>
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={yoyData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="year" stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value: number, name: string) => [`${value.toFixed(1)}%`, name]}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine y={0} stroke="#475569" />
            <Bar dataKey="divergence" fill="#f59e0b" opacity={0.3} name="Divergence" radius={[4, 4, 0, 0]} />
            <Line dataKey="enrollment_change" stroke="#10b981" strokeWidth={2} dot={{ r: 3, fill: '#10b981' }} name="Enrollment Growth" />
            <Line dataKey="billing_change" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: '#3b82f6' }} name="Billing Growth" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function TrendDivergence() {
  const [selectedState, setSelectedState] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['trend-divergence'],
    queryFn: () => api.trendDivergence(),
    staleTime: 60_000,
  })

  if (isLoading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-gray-400 text-sm">Loading trend data...</div>
    </div>
  )
  if (error) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-red-400 text-sm">Error loading trends: {(error as Error).message}</div>
    </div>
  )
  if (!data) return null

  const { summary, states } = data
  const selectedRecord = states.find(s => s.state === selectedState)
  const statesWithData = states.filter(s => s.has_billing_data)
  const top10 = statesWithData.slice(0, 10)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">State Enrollment vs Billing Trends</h1>
        <p className="text-sm text-gray-400 mt-1">
          Compare Medicaid enrollment growth against billing growth per state.
          Billing growing faster than enrollment may indicate fraud.
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="States with Divergence"
          value={summary.states_flagged}
          sub={`of ${summary.states_with_data} states with billing data`}
        />
        <KpiCard
          label="Largest Divergence"
          value={summary.largest_divergence_state ?? 'N/A'}
          sub={summary.largest_divergence_score > 0 ? `Score: ${summary.largest_divergence_score}` : 'No divergence detected'}
        />
        <KpiCard
          label="Avg Billing Growth"
          value={`${summary.avg_billing_growth_pct}%`}
          sub="Mean YoY across states"
        />
        <KpiCard
          label="Avg Enrollment Growth"
          value={`${summary.avg_enrollment_growth_pct}%`}
          sub="Mean YoY across states"
        />
      </div>

      {/* Top 10 states by divergence — bar chart */}
      {top10.length > 0 && (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Top 10 States by Divergence Score</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={top10} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis type="number" stroke="#64748b" fontSize={11} />
              <YAxis
                type="category"
                dataKey="state"
                stroke="#64748b"
                fontSize={12}
                width={40}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
                formatter={(value: number) => [value.toFixed(1), 'Divergence Score']}
              />
              <Bar
                dataKey="divergence_score"
                radius={[0, 4, 4, 0]}
                cursor="pointer"
                onClick={(d: any) => setSelectedState(d.state)}
              >
                {top10.map((entry) => (
                  <Cell key={entry.state} fill={entry.flagged ? '#ef4444' : '#3b82f6'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-gray-600 mt-2">Click a bar to view detailed state breakdown. Red = flagged divergence.</p>
        </div>
      )}

      {/* State table */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800">
          <h3 className="text-sm font-semibold text-gray-300">All States</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] text-gray-500 uppercase tracking-wider border-b border-gray-800">
                <th className="px-4 py-2 text-left">State</th>
                <th className="px-4 py-2 text-center">Enrollment Trend</th>
                <th className="px-4 py-2 text-center">Billing Trend</th>
                <th className="px-4 py-2 text-right">Divergence Score</th>
                <th className="px-4 py-2 text-right">Consec. Years</th>
                <th className="px-4 py-2 text-center">Flag</th>
              </tr>
            </thead>
            <tbody>
              {states.map(s => (
                <tr
                  key={s.state}
                  onClick={() => setSelectedState(selectedState === s.state ? null : s.state)}
                  className={`border-b border-gray-800/50 cursor-pointer transition-colors
                    ${selectedState === s.state ? 'bg-blue-900/20' : 'hover:bg-gray-800/50'}
                    ${!s.has_billing_data ? 'opacity-40' : ''}`}
                >
                  <td className="px-4 py-2 font-mono font-semibold text-white">{s.state}</td>
                  <td className="px-4 py-2 text-center"><TrendArrow direction={s.enrollment_trend} /></td>
                  <td className="px-4 py-2 text-center"><TrendArrow direction={s.billing_trend} /></td>
                  <td className="px-4 py-2 text-right font-mono">
                    {s.has_billing_data ? s.divergence_score.toFixed(1) : '--'}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {s.has_billing_data ? s.consecutive_divergent_years : '--'}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {s.flagged ? (
                      <span className="inline-block px-2 py-0.5 bg-red-900/40 text-red-400 text-[10px] font-bold uppercase rounded">
                        Flagged
                      </span>
                    ) : s.has_billing_data ? (
                      <span className="text-gray-600 text-xs">--</span>
                    ) : (
                      <span className="text-gray-700 text-[10px]">No data</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail panel for selected state */}
      {selectedRecord && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-bold text-white">
              {selectedRecord.state} — Detailed Breakdown
              {selectedRecord.flagged && (
                <span className="ml-3 inline-block px-2 py-0.5 bg-red-900/40 text-red-400 text-[10px] font-bold uppercase rounded align-middle">
                  Divergence Flagged
                </span>
              )}
            </h3>
            <button
              onClick={() => setSelectedState(null)}
              className="text-gray-500 hover:text-gray-300 text-sm"
            >
              Close
            </button>
          </div>

          {/* Summary stats for this state */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-gray-800/50 rounded p-3">
              <span className="text-[10px] text-gray-500 uppercase block">Divergence Score</span>
              <span className="text-lg font-bold text-white">{selectedRecord.divergence_score.toFixed(1)}</span>
            </div>
            <div className="bg-gray-800/50 rounded p-3">
              <span className="text-[10px] text-gray-500 uppercase block">Consec. Divergent Years</span>
              <span className="text-lg font-bold text-white">{selectedRecord.consecutive_divergent_years}</span>
            </div>
            <div className="bg-gray-800/50 rounded p-3">
              <span className="text-[10px] text-gray-500 uppercase block">Latest Enrollment</span>
              <span className="text-lg font-bold text-white">
                {selectedRecord.yearly[selectedRecord.yearly.length - 1]?.enrollment_millions}M
              </span>
            </div>
          </div>

          {selectedRecord.has_billing_data ? (
            <StateDetailChart record={selectedRecord} />
          ) : (
            <div className="text-center py-12 text-gray-500 text-sm">
              No billing data available for {selectedRecord.state}. Scan providers in this state to populate trends.
            </div>
          )}

          {/* Yearly data table */}
          <div className="mt-6">
            <h4 className="text-sm font-semibold text-gray-300 mb-3">Yearly Data</h4>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] text-gray-500 uppercase tracking-wider border-b border-gray-800">
                  <th className="px-3 py-2 text-left">Year</th>
                  <th className="px-3 py-2 text-right">Enrollment (M)</th>
                  <th className="px-3 py-2 text-right">Total Billing</th>
                  <th className="px-3 py-2 text-right">$/Enrollee</th>
                  <th className="px-3 py-2 text-right">Enroll. Change</th>
                  <th className="px-3 py-2 text-right">Billing Change</th>
                  <th className="px-3 py-2 text-right">Divergence</th>
                </tr>
              </thead>
              <tbody>
                {selectedRecord.yearly.map((y, i) => {
                  const yoy = selectedRecord.yoy.find(yo => yo.year === y.year)
                  return (
                    <tr
                      key={y.year}
                      className={`border-b border-gray-800/50 ${yoy?.is_divergent ? 'bg-red-900/10' : ''}`}
                    >
                      <td className="px-3 py-1.5 font-mono text-white">{y.year}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-gray-300">{y.enrollment_millions}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-gray-300">{y.total_billing > 0 ? fmt(y.total_billing) : '--'}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-gray-300">{y.billing_per_enrollee > 0 ? `$${y.billing_per_enrollee.toFixed(2)}` : '--'}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                        {yoy ? `${yoy.enrollment_change_pct > 0 ? '+' : ''}${yoy.enrollment_change_pct}%` : '--'}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                        {yoy ? `${yoy.billing_change_pct > 0 ? '+' : ''}${yoy.billing_change_pct}%` : '--'}
                      </td>
                      <td className={`px-3 py-1.5 text-right font-mono font-semibold ${yoy?.is_divergent ? 'text-red-400' : 'text-gray-500'}`}>
                        {yoy ? `${yoy.divergence_pct > 0 ? '+' : ''}${yoy.divergence_pct}%` : '--'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
