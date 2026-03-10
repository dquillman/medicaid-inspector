import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { api } from '../lib/api'

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v?.toFixed(2) ?? 0}`
}

function PercentileGauge({ value, label }: { value: number; label: string }) {
  const color =
    value >= 95 ? '#ef4444' :
    value >= 90 ? '#f97316' :
    value >= 75 ? '#eab308' :
    value >= 50 ? '#3b82f6' :
    '#22c55e'

  const bgColor =
    value >= 95 ? 'bg-red-950 border-red-800' :
    value >= 90 ? 'bg-orange-950 border-orange-800' :
    value >= 75 ? 'bg-yellow-950 border-yellow-800' :
    value >= 50 ? 'bg-blue-950 border-blue-800' :
    'bg-green-950 border-green-800'

  return (
    <div className={`rounded-lg border px-4 py-3 ${bgColor}`}>
      <p className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{label}</p>
      <div className="flex items-end gap-2 mt-1">
        <span className="text-2xl font-bold font-mono" style={{ color }}>
          {value.toFixed(0)}
        </span>
        <span className="text-xs text-gray-500 pb-1">th percentile</span>
      </div>
      <div className="mt-2 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${value}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

function ComparisonRow({ label, providerVal, avg, median, p75, p90, p95, money = true }: {
  label: string
  providerVal: number
  avg: number
  median: number
  p75: number
  p90: number
  p95: number
  money?: boolean
}) {
  const fv = (v: number) => money ? fmt(v) : v.toLocaleString()
  const exceeds90 = providerVal > p90
  const exceeds75 = providerVal > p75

  return (
    <tr className={`border-b border-gray-800 text-sm ${
      exceeds90 ? 'bg-red-950/30' : exceeds75 ? 'bg-yellow-950/20' : ''
    }`}>
      <td className="py-2.5 pr-4 text-gray-400 font-medium">{label}</td>
      <td className="py-2.5 pr-4 font-mono text-white font-bold">{fv(providerVal)}</td>
      <td className="py-2.5 pr-4 font-mono text-gray-500">{fv(avg)}</td>
      <td className="py-2.5 pr-4 font-mono text-gray-500">{fv(median)}</td>
      <td className="py-2.5 pr-4 font-mono text-gray-500">{fv(p75)}</td>
      <td className="py-2.5 pr-4 font-mono text-gray-500">{fv(p90)}</td>
      <td className="py-2.5 font-mono text-gray-500">{fv(p95)}</td>
    </tr>
  )
}

export default function SpecialtyBenchmark({ npi }: { npi: string }) {
  const { data: rankData, isLoading } = useQuery({
    queryKey: ['specialty-rank', npi],
    queryFn: () => api.providerSpecialtyRank(npi),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const specialty = rankData?.specialty
  const { data: outlierData } = useQuery({
    queryKey: ['specialty-outliers', specialty],
    queryFn: () => api.specialtyOutliers(specialty!, 10),
    enabled: !!specialty && (rankData?.provider_count ?? 0) >= 2,
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Specialty Benchmark</h2>
        <div className="h-32 flex items-center justify-center text-gray-600 text-sm">Loading specialty data...</div>
      </div>
    )
  }

  if (!rankData || rankData.note || !rankData.percentiles || !rankData.stats) {
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Specialty Benchmark</h2>
        <p className="text-sm text-gray-500">
          {rankData?.note || 'Specialty benchmarking data unavailable for this provider.'}
        </p>
        {rankData?.specialty && (
          <p className="text-xs text-gray-600 mt-1">Specialty: {rankData.specialty}</p>
        )}
      </div>
    )
  }

  const { percentiles, stats, this_provider } = rankData
  const provCount = rankData.provider_count

  // Build distribution chart data: compare provider values vs specialty benchmarks
  const chartData = [
    { name: 'This Provider', value: this_provider!.total_paid, fill: '#3b82f6' },
    { name: 'Avg', value: stats.avg_paid, fill: '#6b7280' },
    { name: 'Median', value: stats.median_paid, fill: '#6b7280' },
    { name: 'P75', value: stats.p75_paid, fill: '#854d0e' },
    { name: 'P90', value: stats.p90_paid, fill: '#b45309' },
    { name: 'P95', value: stats.p95_paid, fill: '#991b1b' },
  ]

  // Find the outlier entry for this provider
  const thisOutlier = outlierData?.outliers?.find(o => o.npi === npi)

  // Top outliers excluding current provider
  const topOutliers = (outlierData?.outliers || [])
    .filter(o => o.npi !== npi && o.z_score > 1.5)
    .slice(0, 5)

  return (
    <div className="card bg-indigo-950/20 border-indigo-900/40">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-300">Specialty Benchmark</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Compared to <span className="text-gray-300 font-medium">{provCount.toLocaleString()}</span> providers
            in <span className="text-indigo-400 font-medium">{rankData.specialty}</span>
          </p>
        </div>
        {thisOutlier && Math.abs(thisOutlier.z_score) > 2 && (
          <span className="text-xs px-2.5 py-1 bg-red-900 border border-red-700 rounded-full text-red-300 font-bold">
            Z-SCORE: {thisOutlier.z_score.toFixed(1)}
          </span>
        )}
      </div>

      {/* Percentile Gauges */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        <PercentileGauge value={percentiles.total_paid} label="Total Paid Rank" />
        <PercentileGauge value={percentiles.total_claims} label="Total Claims Rank" />
        <PercentileGauge value={percentiles.total_beneficiaries} label="Beneficiaries Rank" />
      </div>

      {/* Comparison Table */}
      <div className="mb-5">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Provider vs Specialty Benchmarks
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-[10px] text-gray-500 border-b border-gray-800 uppercase tracking-wider">
                <th className="text-left pb-2 pr-4 font-medium">Metric</th>
                <th className="text-left pb-2 pr-4 font-medium">This Provider</th>
                <th className="text-left pb-2 pr-4 font-medium">Avg</th>
                <th className="text-left pb-2 pr-4 font-medium">Median</th>
                <th className="text-left pb-2 pr-4 font-medium">P75</th>
                <th className="text-left pb-2 pr-4 font-medium">P90</th>
                <th className="text-left pb-2 font-medium">P95</th>
              </tr>
            </thead>
            <tbody>
              <ComparisonRow
                label="Total Paid"
                providerVal={this_provider!.total_paid}
                avg={stats.avg_paid}
                median={stats.median_paid}
                p75={stats.p75_paid}
                p90={stats.p90_paid}
                p95={stats.p95_paid}
              />
              <ComparisonRow
                label="Total Claims"
                providerVal={this_provider!.total_claims}
                avg={stats.avg_claims}
                median={stats.median_claims}
                p75={stats.p75_claims}
                p90={stats.p90_claims}
                p95={stats.p90_claims}
                money={false}
              />
              <ComparisonRow
                label="Beneficiaries"
                providerVal={this_provider!.total_beneficiaries}
                avg={stats.median_beneficiaries}
                median={stats.median_beneficiaries}
                p75={stats.p75_beneficiaries}
                p90={stats.p90_beneficiaries}
                p95={stats.p90_beneficiaries}
                money={false}
              />
            </tbody>
          </table>
        </div>
      </div>

      {/* Bar Chart: Provider vs Specialty Distribution */}
      <div className="mb-5">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Total Paid: Provider vs Specialty Benchmarks
        </h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
            <XAxis
              dataKey="name"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tick={{ fill: '#6b7280', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={60}
              tickFormatter={(v: number) => {
                if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
                if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
                return `$${v}`
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: '1px solid #374151',
                borderRadius: '8px',
                fontSize: '12px',
              }}
              labelStyle={{ color: '#9ca3af' }}
              formatter={(value: number) => [fmt(value), 'Amount']}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, idx) => (
                <Cell key={idx} fill={entry.fill} opacity={idx === 0 ? 1 : 0.7} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Top Outliers in Same Specialty */}
      {topOutliers.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Top Outliers in {rankData.specialty}
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] text-gray-500 border-b border-gray-800 uppercase tracking-wider">
                  <th className="text-left pb-2 pr-4 font-medium">NPI</th>
                  <th className="text-left pb-2 pr-4 font-medium">Name</th>
                  <th className="text-left pb-2 pr-4 font-medium">State</th>
                  <th className="text-left pb-2 pr-4 font-medium">Total Paid</th>
                  <th className="text-left pb-2 pr-4 font-medium">Z-Score</th>
                  <th className="text-left pb-2 font-medium">Risk</th>
                </tr>
              </thead>
              <tbody>
                {topOutliers.map(o => (
                  <tr key={o.npi} className="border-b border-gray-800 hover:bg-gray-800/30">
                    <td className="py-2 pr-4">
                      <Link
                        to={`/providers/${o.npi}`}
                        className="font-mono text-xs text-blue-400 hover:text-blue-300 underline"
                      >
                        {o.npi}
                      </Link>
                    </td>
                    <td className="py-2 pr-4 text-gray-300 text-xs max-w-[160px] truncate" title={o.provider_name}>
                      {o.provider_name || '--'}
                    </td>
                    <td className="py-2 pr-4 text-gray-500 text-xs">{o.state || '--'}</td>
                    <td className="py-2 pr-4 font-mono text-gray-300 text-xs">{fmt(o.total_paid)}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
                        o.z_score >= 3 ? 'bg-red-900 text-red-300' :
                        o.z_score >= 2 ? 'bg-orange-900 text-orange-300' :
                        'bg-yellow-900 text-yellow-300'
                      }`}>
                        {o.z_score.toFixed(1)}
                      </span>
                    </td>
                    <td className="py-2">
                      <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
                        o.risk_score >= 75 ? 'bg-red-900 text-red-300' :
                        o.risk_score >= 50 ? 'bg-orange-900 text-orange-300' :
                        'bg-gray-800 text-gray-400'
                      }`}>
                        {o.risk_score.toFixed(0)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
