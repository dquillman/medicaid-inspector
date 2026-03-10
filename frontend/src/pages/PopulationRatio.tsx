import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer, Cell } from 'recharts'
import { api } from '../lib/api'

type SortField = 'state' | 'provider_count' | 'enrollment' | 'providers_per_100k' | 'total_paid' | 'avg_risk_score'
type CapSortField = 'provider_name' | 'state' | 'total_paid' | 'estimated_max' | 'overage_pct' | 'risk_score'

export default function PopulationRatio() {
  const [tab, setTab] = useState<'density' | 'capacity'>('density')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Provider-to-Population Analysis</h1>
        <p className="text-sm text-gray-400 mt-1">
          Identify geographic areas with suspicious provider density and providers billing beyond physical capacity
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-800/50 p-1 rounded-lg w-fit">
        <button
          onClick={() => setTab('density')}
          className={tab === 'density' ? 'btn-primary' : 'btn-ghost'}
        >
          Provider Density
        </button>
        <button
          onClick={() => setTab('capacity')}
          className={tab === 'capacity' ? 'btn-primary' : 'btn-ghost'}
        >
          Over-Capacity Providers
        </button>
      </div>

      {tab === 'density' ? <DensityTab /> : <CapacityTab />}
    </div>
  )
}

/* ── Provider Density Tab ──────────────────────────────────────────────── */

function DensityTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['population-ratios'],
    queryFn: api.populationRatios,
  })

  const [sortField, setSortField] = useState<SortField>('providers_per_100k')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  if (isLoading) return <div className="text-gray-400">Loading ratios...</div>
  if (error) return <div className="text-red-400">Error loading data</div>
  if (!data || !data.states.length) return <div className="text-gray-400">No provider data available. Run a scan first.</div>

  const toggleSort = (field: SortField) => {
    if (sortField === field) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortDir('desc') }
  }

  const sorted = [...data.states].sort((a, b) => {
    const av = a[sortField] ?? 0
    const bv = b[sortField] ?? 0
    if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number)
  })

  // Top 15 states for bar chart
  const chartData = [...data.states]
    .sort((a, b) => b.providers_per_100k - a.providers_per_100k)
    .slice(0, 15)

  const SortIcon = ({ field }: { field: SortField }) => (
    <span className="ml-1 text-gray-600">
      {sortField === field ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : '\u25BC'}
    </span>
  )

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">States with Data</div>
          <div className="text-2xl font-bold text-white mt-1">{data.states.length}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Total Providers</div>
          <div className="text-2xl font-bold text-white mt-1">{data.total_providers.toLocaleString()}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">National Avg / 100k</div>
          <div className="text-2xl font-bold text-blue-400 mt-1">{data.national_avg_per_100k.toFixed(1)}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Flagged States ({'>'}2x Avg)</div>
          <div className="text-2xl font-bold text-red-400 mt-1">{data.states.filter((s: any) => s.flagged).length}</div>
        </div>
      </div>

      {/* Bar chart */}
      <div className="card p-4">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Top 15 States by Providers per 100k Enrollees</h2>
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="state" tick={{ fill: '#9ca3af', fontSize: 12 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              labelStyle={{ color: '#f3f4f6' }}
              itemStyle={{ color: '#60a5fa' }}
              formatter={(value: number) => [value.toFixed(1), 'Per 100k']}
            />
            <ReferenceLine
              y={data.national_avg_per_100k}
              stroke="#f59e0b"
              strokeDasharray="5 5"
              label={{ value: `Nat'l Avg: ${data.national_avg_per_100k.toFixed(1)}`, fill: '#f59e0b', fontSize: 11, position: 'right' }}
            />
            <Bar dataKey="providers_per_100k" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, idx) => (
                <Cell
                  key={idx}
                  fill={entry.flagged ? '#ef4444' : '#3b82f6'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="flex gap-4 mt-2 text-xs text-gray-500 justify-center">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500 inline-block" /> Flagged ({'>'}2x national avg)</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-500 inline-block" /> Normal</span>
          <span className="flex items-center gap-1"><span className="w-6 border-t-2 border-dashed border-amber-500 inline-block" /> National Average</span>
        </div>
      </div>

      {/* State table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-3 text-left cursor-pointer hover:text-gray-200" onClick={() => toggleSort('state')}>
                State<SortIcon field="state" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('provider_count')}>
                Providers<SortIcon field="provider_count" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('enrollment')}>
                Enrollment<SortIcon field="enrollment" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('providers_per_100k')}>
                Per 100k<SortIcon field="providers_per_100k" />
              </th>
              <th className="px-4 py-3 text-center">vs National</th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('total_paid')}>
                Total Paid<SortIcon field="total_paid" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('avg_risk_score')}>
                Avg Risk<SortIcon field="avg_risk_score" />
              </th>
              <th className="px-4 py-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.state} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="px-4 py-2.5 font-medium text-white">{row.state}</td>
                <td className="px-4 py-2.5 text-right text-gray-300">{row.provider_count.toLocaleString()}</td>
                <td className="px-4 py-2.5 text-right text-gray-300">{row.enrollment.toLocaleString()}</td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-200">{row.providers_per_100k.toFixed(1)}</td>
                <td className="px-4 py-2.5 text-center">
                  <span className={`font-mono text-xs ${row.ratio_vs_national > 2 ? 'text-red-400' : row.ratio_vs_national > 1.5 ? 'text-amber-400' : 'text-gray-400'}`}>
                    {row.ratio_vs_national.toFixed(1)}x
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right text-gray-300">${(row.total_paid / 1_000_000).toFixed(1)}M</td>
                <td className="px-4 py-2.5 text-right">
                  <span className={`${row.avg_risk_score >= 50 ? 'text-red-400' : row.avg_risk_score >= 25 ? 'text-amber-400' : 'text-green-400'}`}>
                    {row.avg_risk_score.toFixed(0)}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-center">
                  {row.flagged ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                      FLAGGED
                    </span>
                  ) : (
                    <span className="text-xs text-gray-600">Normal</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ── Over-Capacity Providers Tab ───────────────────────────────────────── */

function CapacityTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['population-overcapacity'],
    queryFn: api.populationOvercapacity,
  })

  const [sortField, setSortField] = useState<CapSortField>('overage_pct')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  if (isLoading) return <div className="text-gray-400">Loading capacity analysis...</div>
  if (error) return <div className="text-red-400">Error loading data</div>
  if (!data || !data.providers.length) return <div className="text-gray-400">No over-capacity providers found.</div>

  const toggleSort = (field: CapSortField) => {
    if (sortField === field) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortDir('desc') }
  }

  const sorted = [...data.providers].sort((a, b) => {
    const av = a[sortField] ?? 0
    const bv = b[sortField] ?? 0
    if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number)
  })

  const SortIcon = ({ field }: { field: CapSortField }) => (
    <span className="ml-1 text-gray-600">
      {sortField === field ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : '\u25BC'}
    </span>
  )

  const totalOverage = data.providers.reduce((s: number, p: any) => s + p.overage_amount, 0)

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Over-Capacity Providers</div>
          <div className="text-2xl font-bold text-red-400 mt-1">{data.total}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Total Overage Amount</div>
          <div className="text-2xl font-bold text-amber-400 mt-1">${(totalOverage / 1_000_000).toFixed(1)}M</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Capacity Threshold</div>
          <div className="text-2xl font-bold text-gray-300 mt-1">$600K/yr</div>
          <div className="text-xs text-gray-500 mt-0.5">16 pts/day x 250 days x $150 avg</div>
        </div>
      </div>

      {/* Info banner */}
      <div className="card p-3 bg-blue-500/5 border-blue-500/20">
        <p className="text-xs text-blue-300">
          Providers billing beyond an estimated solo-practitioner capacity of $600,000/year
          (16 patients/day, 250 working days, $150 average visit). This does not necessarily
          indicate fraud -- group practices and high-volume specialties may legitimately exceed
          this threshold. Manual review is recommended.
        </p>
      </div>

      {/* Provider table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-3 text-left">NPI</th>
              <th className="px-4 py-3 text-left cursor-pointer hover:text-gray-200" onClick={() => toggleSort('provider_name')}>
                Provider<SortIcon field="provider_name" />
              </th>
              <th className="px-4 py-3 text-center cursor-pointer hover:text-gray-200" onClick={() => toggleSort('state')}>
                State<SortIcon field="state" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('total_paid')}>
                Total Paid<SortIcon field="total_paid" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('estimated_max')}>
                Est. Max<SortIcon field="estimated_max" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('overage_pct')}>
                Overage %<SortIcon field="overage_pct" />
              </th>
              <th className="px-4 py-3 text-right cursor-pointer hover:text-gray-200" onClick={() => toggleSort('risk_score')}>
                Risk<SortIcon field="risk_score" />
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={p.npi} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="px-4 py-2.5">
                  <Link to={`/providers/${p.npi}`} className="font-mono text-blue-400 hover:text-blue-300 hover:underline">
                    {p.npi}
                  </Link>
                </td>
                <td className="px-4 py-2.5 text-gray-200 max-w-[200px] truncate" title={p.provider_name}>
                  {p.provider_name}
                </td>
                <td className="px-4 py-2.5 text-center text-gray-300">{p.state}</td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-200">
                  ${(p.total_paid / 1_000).toFixed(0)}K
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-400">
                  ${(p.estimated_max / 1_000).toFixed(0)}K
                </td>
                <td className="px-4 py-2.5 text-right">
                  <span className={`font-mono font-medium ${
                    p.overage_pct > 500 ? 'text-red-400' : p.overage_pct > 200 ? 'text-amber-400' : 'text-yellow-400'
                  }`}>
                    +{p.overage_pct.toFixed(0)}%
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    p.risk_score >= 50 ? 'bg-red-500/20 text-red-400' :
                    p.risk_score >= 25 ? 'bg-amber-500/20 text-amber-400' :
                    'bg-gray-700 text-gray-300'
                  }`}>
                    {p.risk_score}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
