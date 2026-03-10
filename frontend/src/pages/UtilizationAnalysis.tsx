import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

type Tab = 'states' | 'outliers'

function fmt(n: number): string {
  return n.toLocaleString()
}

function fmtDollar(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

export default function UtilizationAnalysis() {
  const [tab, setTab] = useState<Tab>('states')
  const navigate = useNavigate()

  const statesQuery = useQuery({
    queryKey: ['utilization-by-state'],
    queryFn: () => api.utilizationByState(),
  })

  const outliersQuery = useQuery({
    queryKey: ['utilization-outliers'],
    queryFn: () => api.utilizationOutliers(50),
  })

  const statesData = statesQuery.data
  const outliersData = outliersQuery.data

  // Chart data: top 10 states by claims_per_1000
  const chartData = (statesData?.states || [])
    .slice(0, 10)
    .map((s) => ({
      state: s.state,
      claims_per_1000: s.claims_per_1000,
      national_avg: s.national_avg_claims_per_1000,
    }))

  const nationalAvg = statesData?.states?.[0]?.national_avg_claims_per_1000 || 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">
          Expected vs Actual Utilization
        </h1>
        <p className="text-sm text-gray-400 mt-1">
          Compare provider claims volume against state/county expected Medicaid
          utilization rates to identify phantom billing and over-utilization.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1">
        <button
          onClick={() => setTab('states')}
          className={tab === 'states' ? 'btn-primary' : 'btn-ghost'}
        >
          State View
        </button>
        <button
          onClick={() => setTab('outliers')}
          className={tab === 'outliers' ? 'btn-primary' : 'btn-ghost'}
        >
          Provider Outliers
        </button>
      </div>

      {tab === 'states' && (
        <div className="space-y-6">
          {/* Summary cards */}
          {statesData && (
            <div className="grid grid-cols-3 gap-4">
              <div className="card p-4">
                <div className="text-xs text-gray-500 uppercase tracking-wider">
                  States with Data
                </div>
                <div className="text-2xl font-bold text-white mt-1">
                  {statesData.total_states}
                </div>
              </div>
              <div className="card p-4">
                <div className="text-xs text-gray-500 uppercase tracking-wider">
                  Flagged States (&gt;2x Avg)
                </div>
                <div className="text-2xl font-bold text-red-400 mt-1">
                  {statesData.flagged_states}
                </div>
              </div>
              <div className="card p-4">
                <div className="text-xs text-gray-500 uppercase tracking-wider">
                  National Avg Claims/1K
                </div>
                <div className="text-2xl font-bold text-blue-400 mt-1">
                  {nationalAvg.toFixed(1)}
                </div>
              </div>
            </div>
          )}

          {/* Bar chart — Top 10 states */}
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">
              Top 10 States: Claims per 1,000 Enrollees vs National Average
            </h2>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={360}>
                <BarChart
                  data={chartData}
                  margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="state" tick={{ fill: '#9ca3af', fontSize: 12 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1f2937',
                      border: '1px solid #374151',
                      borderRadius: '6px',
                      color: '#e5e7eb',
                    }}
                    formatter={(value: number, name: string) => [
                      value.toFixed(1),
                      name === 'claims_per_1000'
                        ? 'Claims/1K Enrollees'
                        : 'National Avg',
                    ]}
                  />
                  <Legend
                    formatter={(value: string) =>
                      value === 'claims_per_1000'
                        ? 'Claims/1K Enrollees'
                        : 'National Avg'
                    }
                  />
                  <Bar
                    dataKey="claims_per_1000"
                    fill="#3b82f6"
                    radius={[4, 4, 0, 0]}
                  />
                  <ReferenceLine
                    y={nationalAvg}
                    stroke="#ef4444"
                    strokeDasharray="5 5"
                    strokeWidth={2}
                    label={{
                      value: `Nat'l Avg: ${nationalAvg.toFixed(1)}`,
                      fill: '#ef4444',
                      fontSize: 11,
                      position: 'insideTopRight',
                    }}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-gray-500 text-sm text-center py-12">
                No state data available. Run a scan first.
              </div>
            )}
          </div>

          {/* State table */}
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">State</th>
                  <th className="text-right px-4 py-3">Enrollment</th>
                  <th className="text-right px-4 py-3">Providers</th>
                  <th className="text-right px-4 py-3">Total Claims</th>
                  <th className="text-right px-4 py-3">Total Paid</th>
                  <th className="text-right px-4 py-3">Claims/1K</th>
                  <th className="text-right px-4 py-3">Nat'l Avg</th>
                  <th className="text-right px-4 py-3">Deviation</th>
                  <th className="text-center px-4 py-3">Flag</th>
                </tr>
              </thead>
              <tbody>
                {statesQuery.isLoading && (
                  <tr>
                    <td colSpan={9} className="text-center py-8 text-gray-500">
                      Loading...
                    </td>
                  </tr>
                )}
                {statesData?.states.map((s) => (
                  <tr
                    key={s.state}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer transition-colors"
                    onClick={() => navigate(`/utilization?state=${s.state}`)}
                  >
                    <td className="px-4 py-2.5 font-medium text-white">
                      {s.state}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      {fmt(s.enrollment)}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      {fmt(s.provider_count)}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      {fmt(s.total_claims)}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      {fmtDollar(s.total_paid)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono font-medium text-white">
                      {s.claims_per_1000.toFixed(1)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-gray-500">
                      {s.national_avg_claims_per_1000.toFixed(1)}
                    </td>
                    <td
                      className={`px-4 py-2.5 text-right font-mono font-medium ${
                        s.deviation_pct > 100
                          ? 'text-red-400'
                          : s.deviation_pct > 50
                          ? 'text-yellow-400'
                          : s.deviation_pct > 0
                          ? 'text-green-400'
                          : 'text-gray-400'
                      }`}
                    >
                      {s.deviation_pct > 0 ? '+' : ''}
                      {s.deviation_pct.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {s.flagged ? (
                        <span className="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-red-900/50 text-red-300 border border-red-800">
                          FLAGGED
                        </span>
                      ) : (
                        <span className="text-gray-600">--</span>
                      )}
                    </td>
                  </tr>
                ))}
                {statesData && statesData.states.length === 0 && (
                  <tr>
                    <td colSpan={9} className="text-center py-8 text-gray-500">
                      No state data. Run a scan to populate provider data.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'outliers' && (
        <div className="space-y-4">
          {outliersData && (
            <div className="text-sm text-gray-400">
              Showing {outliersData.total} providers exceeding 3x their
              state-specialty average utilization
            </div>
          )}

          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">NPI</th>
                  <th className="text-left px-4 py-3">Provider</th>
                  <th className="text-center px-4 py-3">State</th>
                  <th className="text-left px-4 py-3">Specialty</th>
                  <th className="text-right px-4 py-3">Claims</th>
                  <th className="text-right px-4 py-3">Expected</th>
                  <th className="text-right px-4 py-3">Total Paid</th>
                  <th className="text-right px-4 py-3">Deviation</th>
                  <th className="text-right px-4 py-3">Risk</th>
                </tr>
              </thead>
              <tbody>
                {outliersQuery.isLoading && (
                  <tr>
                    <td colSpan={9} className="text-center py-8 text-gray-500">
                      Loading...
                    </td>
                  </tr>
                )}
                {outliersData?.outliers.map((o) => (
                  <tr
                    key={o.npi}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer transition-colors"
                    onClick={() => navigate(`/providers/${o.npi}`)}
                  >
                    <td className="px-4 py-2.5 font-mono text-blue-400 hover:underline">
                      {o.npi}
                    </td>
                    <td className="px-4 py-2.5 text-white max-w-[200px] truncate">
                      {o.provider_name}
                    </td>
                    <td className="px-4 py-2.5 text-center text-gray-300">
                      {o.state}
                    </td>
                    <td className="px-4 py-2.5 text-gray-400 max-w-[180px] truncate">
                      {o.specialty}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-white">
                      {fmt(o.total_claims)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-gray-500">
                      {fmt(Math.round(o.expected_claims))}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      {fmtDollar(o.total_paid)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={`inline-block px-2 py-0.5 rounded font-mono font-bold text-xs ${
                          o.deviation_multiple >= 10
                            ? 'bg-red-900/60 text-red-300 border border-red-700'
                            : o.deviation_multiple >= 5
                            ? 'bg-yellow-900/60 text-yellow-300 border border-yellow-700'
                            : 'bg-blue-900/40 text-blue-300 border border-blue-800'
                        }`}
                      >
                        {o.deviation_multiple.toFixed(1)}x
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={`font-mono font-bold ${
                          o.risk_score >= 50
                            ? 'text-red-400'
                            : o.risk_score >= 10
                            ? 'text-yellow-400'
                            : 'text-green-400'
                        }`}
                      >
                        {o.risk_score}
                      </span>
                    </td>
                  </tr>
                ))}
                {outliersData && outliersData.outliers.length === 0 && (
                  <tr>
                    <td colSpan={9} className="text-center py-8 text-gray-500">
                      No outlier providers found. Run a scan to populate data or
                      lower detection thresholds.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
