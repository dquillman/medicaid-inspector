import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'
import type { MetricDistribution } from '../lib/types'

interface Props {
  distributions: MetricDistribution[]
}

function fmtValue(v: number, metric: string) {
  if (metric === 'claims_per_beneficiary') return v.toFixed(1)
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

function fmtBucketLabel(min: number, max: number, metric: string) {
  if (metric === 'claims_per_beneficiary') return `${min.toFixed(0)}-${max.toFixed(0)}`
  if (max >= 1_000_000) return `${(min / 1_000_000).toFixed(1)}M`
  if (max >= 1_000) return `${(min / 1_000).toFixed(0)}K`
  return `$${min.toFixed(0)}`
}

function percentileBadge(pct: number) {
  const bg = pct >= 95 ? 'bg-red-900 text-red-300 border-red-700'
    : pct >= 75 ? 'bg-yellow-900 text-yellow-300 border-yellow-700'
    : 'bg-green-900 text-green-300 border-green-800'
  return (
    <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${bg}`}>
      {pct.toFixed(0)}th percentile
    </span>
  )
}

function bucketColor(bucketMax: number, p75Val: number, p95Val: number) {
  if (bucketMax >= p95Val) return '#991b1b'  // red-800
  if (bucketMax >= p75Val) return '#854d0e'  // yellow-800
  return '#1e3a5f'                            // blue-dark
}

function DistributionChart({ dist }: { dist: MetricDistribution }) {
  const { buckets, provider_value, percentile, peer_count, metric, label } = dist

  // Compute p75 and p95 values from buckets for coloring
  const totalCount = buckets.reduce((s, b) => s + b.count, 0)
  let cumulative = 0
  let p75Val = buckets[buckets.length - 1].max
  let p95Val = buckets[buckets.length - 1].max
  for (const b of buckets) {
    cumulative += b.count
    if (cumulative / totalCount >= 0.75 && p75Val === buckets[buckets.length - 1].max) {
      p75Val = b.min
    }
    if (cumulative / totalCount >= 0.95 && p95Val === buckets[buckets.length - 1].max) {
      p95Val = b.min
    }
  }

  const chartData = buckets.map(b => ({
    name: fmtBucketLabel(b.min, b.max, metric),
    count: b.count,
    min: b.min,
    max: b.max,
  }))

  // Determine x-axis position for the provider reference line
  // Find which bucket the provider value falls in
  let providerBucketIdx = buckets.findIndex(b => provider_value >= b.min && provider_value < b.max)
  if (providerBucketIdx === -1) providerBucketIdx = buckets.length - 1
  const providerLabel = chartData[providerBucketIdx]?.name ?? ''

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300">{label}</h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">{peer_count.toLocaleString()} peers</span>
          {percentileBadge(percentile)}
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span>This provider: <span className="text-white font-mono font-bold">{fmtValue(provider_value, metric)}</span></span>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            interval="preserveStartEnd"
            tickLine={false}
          />
          <YAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: '12px' }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(value: number) => [value, 'Providers']}
            labelFormatter={(label: string) => `Range: ${label}`}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
            {chartData.map((entry, idx) => (
              <Cell
                key={idx}
                fill={bucketColor(entry.max, p75Val, p95Val)}
                opacity={0.85}
              />
            ))}
          </Bar>
          <ReferenceLine
            x={providerLabel}
            stroke="#ef4444"
            strokeWidth={2}
            strokeDasharray="4 2"
            label={{
              value: 'YOU',
              position: 'top',
              fill: '#ef4444',
              fontSize: 11,
              fontWeight: 'bold',
            }}
          />
        </BarChart>
      </ResponsiveContainer>
      {/* Color legend */}
      <div className="flex items-center gap-4 text-[10px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: '#1e3a5f' }}></span>
          Below 75th %ile
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: '#854d0e' }}></span>
          75th-95th %ile
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: '#991b1b' }}></span>
          Above 95th %ile
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-0.5 h-3 border-l-2 border-dashed border-red-500"></span>
          This Provider
        </span>
      </div>
    </div>
  )
}

export default function PeerBenchmark({ distributions }: Props) {
  if (!distributions || distributions.length === 0) return null

  return (
    <div className="space-y-6">
      {distributions.map(dist => (
        <DistributionChart key={dist.metric} dist={dist} />
      ))}
    </div>
  )
}
