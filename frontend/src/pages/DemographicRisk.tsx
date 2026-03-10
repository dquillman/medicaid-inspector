import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, DemographicState, DemographicStateDetail } from '../lib/api'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ZAxis, Cell,
} from 'recharts'

type SortKey = keyof DemographicState
type SortDir = 'asc' | 'desc'

const fmtNum = (n: number) => n.toLocaleString()
const fmtMoney = (n: number) =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000 ? `$${(n / 1_000).toFixed(1)}K`
      : `$${n.toFixed(0)}`
const fmtPct = (n: number) => `${n.toFixed(1)}%`

function povertyColor(rate: number): string {
  if (rate < 10) return 'text-emerald-400'
  if (rate <= 15) return 'text-yellow-400'
  return 'text-red-400'
}

function riskBadge(score: number) {
  if (score >= 70) return 'bg-red-900/40 text-red-400 border-red-800'
  if (score >= 50) return 'bg-orange-900/30 text-orange-400 border-orange-800'
  if (score >= 30) return 'bg-yellow-900/30 text-yellow-400 border-yellow-800'
  return 'bg-gray-800 text-gray-400 border-gray-700'
}

export default function DemographicRisk() {
  const [sortKey, setSortKey] = useState<SortKey>('demographic_risk_score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [selectedState, setSelectedState] = useState<string | null>(null)

  const { data: riskMap, isLoading } = useQuery({
    queryKey: ['demographic-risk-map'],
    queryFn: api.demographicRiskMap,
    staleTime: 60_000,
  })

  const { data: correlations } = useQuery({
    queryKey: ['demographic-correlations'],
    queryFn: api.demographicCorrelations,
    staleTime: 60_000,
  })

  const { data: stateDetail, isLoading: detailLoading } = useQuery({
    queryKey: ['demographic-state', selectedState],
    queryFn: () => api.demographicStateDetail(selectedState!),
    enabled: !!selectedState,
    staleTime: 60_000,
  })

  const sorted = useMemo(() => {
    if (!riskMap?.states) return []
    const arr = [...riskMap.states]
    arr.sort((a, b) => {
      const av = a[sortKey] as number
      const bv = b[sortKey] as number
      return sortDir === 'asc' ? av - bv : bv - av
    })
    return arr
  }, [riskMap, sortKey, sortDir])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sortIcon = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : ''

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400 animate-pulse">Loading demographic data...</div>
      </div>
    )
  }

  const kpis = riskMap?.kpis

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Demographic Risk Analysis</h1>
        <p className="text-sm text-gray-400 mt-1">
          Census poverty/population data overlaid with provider billing patterns to identify demographic fraud risk factors
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">States at Elevated Risk</div>
          <div className="text-2xl font-bold text-red-400">{kpis?.states_elevated_risk ?? 0}</div>
          <div className="text-xs text-gray-500 mt-1">Demographic risk score &ge; 60</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Highest Correlation Factor</div>
          <div className="text-2xl font-bold text-blue-400">{kpis?.highest_correlation_factor ?? 'N/A'}</div>
          <div className="text-xs text-gray-500 mt-1">
            r = {kpis?.correlation_value?.toFixed(3) ?? '0.000'}
          </div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">National Avg Demographic Risk</div>
          <div className="text-2xl font-bold text-yellow-400">{kpis?.national_avg_demographic_risk?.toFixed(1) ?? '0.0'}</div>
          <div className="text-xs text-gray-500 mt-1">Across all 50 states + DC</div>
        </div>
      </div>

      {/* Scatter Chart */}
      {correlations && correlations.correlations.length > 0 && (
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">
            Poverty Rate vs. Avg Provider Risk Score by State
          </h2>
          <ResponsiveContainer width="100%" height={340}>
            <ScatterChart margin={{ top: 10, right: 30, bottom: 10, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="poverty_rate"
                name="Poverty Rate"
                unit="%"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                label={{ value: 'Poverty Rate (%)', position: 'insideBottom', offset: -5, fill: '#9ca3af', fontSize: 12 }}
              />
              <YAxis
                dataKey="avg_risk_score"
                name="Avg Risk Score"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                label={{ value: 'Avg Risk Score', angle: -90, position: 'insideLeft', fill: '#9ca3af', fontSize: 12 }}
              />
              <ZAxis dataKey="provider_count" range={[40, 400]} name="Providers" />
              <Tooltip
                cursor={{ strokeDasharray: '3 3' }}
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '6px' }}
                labelStyle={{ color: '#e5e7eb' }}
                formatter={(value: number, name: string) => {
                  if (name === 'Poverty Rate') return [`${value.toFixed(1)}%`, name]
                  if (name === 'Avg Risk Score') return [value.toFixed(1), name]
                  return [fmtNum(value), name]
                }}
                labelFormatter={(_, payload) => {
                  if (payload?.[0]?.payload) return payload[0].payload.state
                  return ''
                }}
              />
              <Scatter data={correlations.correlations} onClick={(d) => setSelectedState(d.state)}>
                {correlations.correlations.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={entry.demographic_risk_score >= 70 ? '#ef4444'
                      : entry.demographic_risk_score >= 50 ? '#f59e0b'
                        : entry.demographic_risk_score >= 30 ? '#3b82f6'
                          : '#6b7280'}
                    cursor="pointer"
                  />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* State Detail Drill-down */}
      {selectedState && (
        <StateDetailPanel
          state={selectedState}
          data={stateDetail ?? null}
          loading={detailLoading}
          onClose={() => setSelectedState(null)}
        />
      )}

      {/* Sortable Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
                {([
                  ['state', 'State'],
                  ['population', 'Population'],
                  ['poverty_rate', 'Poverty Rate'],
                  ['median_income', 'Median Income'],
                  ['medicaid_pct', 'Medicaid %'],
                  ['provider_count', 'Providers'],
                  ['avg_risk_score', 'Avg Risk'],
                  ['demographic_risk_score', 'Demo Risk'],
                ] as [SortKey, string][]).map(([key, label]) => (
                  <th
                    key={key}
                    className="px-3 py-2.5 text-left cursor-pointer hover:text-gray-200 transition-colors select-none"
                    onClick={() => toggleSort(key)}
                  >
                    {label}{sortIcon(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr
                  key={s.state}
                  className="border-b border-gray-800/50 hover:bg-gray-800/40 cursor-pointer transition-colors"
                  onClick={() => setSelectedState(s.state)}
                >
                  <td className="px-3 py-2 font-medium text-white">{s.state}</td>
                  <td className="px-3 py-2 text-gray-300">{fmtNum(s.population)}</td>
                  <td className={`px-3 py-2 font-medium ${povertyColor(s.poverty_rate)}`}>
                    {fmtPct(s.poverty_rate)}
                  </td>
                  <td className="px-3 py-2 text-gray-300">{fmtMoney(s.median_income)}</td>
                  <td className="px-3 py-2 text-gray-300">{fmtPct(s.medicaid_pct)}</td>
                  <td className="px-3 py-2 text-gray-300">{fmtNum(s.provider_count)}</td>
                  <td className="px-3 py-2 text-gray-300">{s.avg_risk_score.toFixed(1)}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium border ${riskBadge(s.demographic_risk_score)}`}>
                      {s.demographic_risk_score.toFixed(1)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}


function StateDetailPanel({
  state, data, loading, onClose,
}: {
  state: string
  data: DemographicStateDetail | null
  loading: boolean
  onClose: () => void
}) {
  return (
    <div className="card p-4 border-l-4 border-blue-500">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-bold text-white">
          {state} -- State Detail
        </h2>
        <button onClick={onClose} className="btn-ghost text-xs">Close</button>
      </div>

      {loading && <div className="text-gray-400 animate-pulse">Loading state details...</div>}

      {data && (
        <div className="space-y-4">
          {/* Demographics summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {([
              ['Population', fmtNum(data.population)],
              ['Poverty Rate', fmtPct(data.poverty_rate)],
              ['Median Income', fmtMoney(data.median_income)],
              ['Medicaid %', fmtPct(data.medicaid_pct)],
              ['Uninsured %', fmtPct(data.pct_uninsured)],
              ['Providers Scanned', fmtNum(data.provider_count)],
              ['Avg Risk Score', data.avg_risk_score.toFixed(1)],
              ['Demo Risk Score', data.demographic_risk_score.toFixed(1)],
            ] as [string, string][]).map(([label, value]) => (
              <div key={label} className="bg-gray-800/50 rounded p-2">
                <div className="text-[10px] text-gray-500 uppercase">{label}</div>
                <div className="text-sm font-semibold text-gray-200">{value}</div>
              </div>
            ))}
          </div>

          {/* Provider table */}
          {data.providers.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 uppercase mb-2">
                Top Providers ({data.providers_total} total)
              </h3>
              <div className="overflow-x-auto max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-700 text-gray-500 uppercase">
                      <th className="px-2 py-1.5 text-left">NPI</th>
                      <th className="px-2 py-1.5 text-left">Name</th>
                      <th className="px-2 py-1.5 text-left">City</th>
                      <th className="px-2 py-1.5 text-right">Paid</th>
                      <th className="px-2 py-1.5 text-right">Claims</th>
                      <th className="px-2 py-1.5 text-right">Risk</th>
                      <th className="px-2 py-1.5 text-right">Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.providers.map((p) => (
                      <tr key={p.npi} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                        <td className="px-2 py-1 font-mono text-gray-400">{p.npi}</td>
                        <td className="px-2 py-1 text-gray-300 max-w-[200px] truncate">{p.provider_name || '--'}</td>
                        <td className="px-2 py-1 text-gray-400">{p.city || '--'}</td>
                        <td className="px-2 py-1 text-right text-gray-300">{fmtMoney(p.total_paid)}</td>
                        <td className="px-2 py-1 text-right text-gray-300">{fmtNum(p.total_claims)}</td>
                        <td className="px-2 py-1 text-right">
                          <span className={p.risk_score >= 50 ? 'text-red-400 font-semibold' : 'text-gray-300'}>
                            {p.risk_score.toFixed(1)}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-right text-gray-400">{p.flag_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {data.providers.length === 0 && (
            <p className="text-sm text-gray-500 italic">No providers scanned in this state yet.</p>
          )}
        </div>
      )}
    </div>
  )
}
