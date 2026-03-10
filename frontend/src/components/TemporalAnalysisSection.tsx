import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'
import { api } from '../lib/api'
import type { TemporalAnalysis, TemporalAnomaly } from '../lib/types'

function fmt(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v?.toFixed(0) ?? 0}`
}

const SEVERITY_COLORS: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  CRITICAL: { bg: 'bg-red-950/40', border: 'border-red-700', text: 'text-red-300', dot: '#ef4444' },
  HIGH:     { bg: 'bg-orange-950/40', border: 'border-orange-700', text: 'text-orange-300', dot: '#f97316' },
  MEDIUM:   { bg: 'bg-yellow-950/40', border: 'border-yellow-700', text: 'text-yellow-300', dot: '#eab308' },
  LOW:      { bg: 'bg-gray-800/40', border: 'border-gray-700', text: 'text-gray-400', dot: '#6b7280' },
}

const ANOMALY_TYPE_LABELS: Record<string, string> = {
  billing_spike: 'Billing Spike',
  billing_drop: 'Billing Drop',
  impossible_volume: 'Impossible Volume',
  seasonal_anomaly: 'Seasonal Anomaly',
  practice_change: 'Practice Change',
  volume_spike: 'Volume Surge',
  volume_drop: 'Volume Drop',
}

function SeverityBadge({ severity }: { severity: string }) {
  const s = SEVERITY_COLORS[severity] || SEVERITY_COLORS.LOW
  return (
    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${s.bg} ${s.border} ${s.text}`}>
      {severity}
    </span>
  )
}

function AnomalyTypeBadge({ type }: { type: string }) {
  const label = ANOMALY_TYPE_LABELS[type] || type.replace(/_/g, ' ')
  const isVolumeIssue = type === 'impossible_volume'
  const isPracticeChange = type === 'practice_change'
  return (
    <span className={`text-[10px] font-medium uppercase px-2 py-0.5 rounded border ${
      isVolumeIssue
        ? 'bg-red-900/30 border-red-800 text-red-400'
        : isPracticeChange
          ? 'bg-purple-900/30 border-purple-800 text-purple-400'
          : 'bg-blue-900/30 border-blue-800 text-blue-400'
    }`}>
      {label}
    </span>
  )
}

function DayOfWeekChart({ data }: { data: TemporalAnalysis['day_of_week_distribution'] }) {
  if (!data || data.length === 0) return null

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Estimated Day-of-Week Distribution
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="day"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickFormatter={(v: string) => v.slice(0, 3)}
          />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <Tooltip
            contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#e5e7eb' }}
            formatter={(value: number, _name: string, props: any) => [
              `${value} claims (est.)`,
              props?.payload?.is_weekend ? 'Weekend' : 'Weekday',
            ]}
          />
          <Bar dataKey="estimated_claims" radius={[4, 4, 0, 0]}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.is_weekend
                  ? (entry.is_anomalous ? '#ef4444' : '#f59e0b')
                  : (entry.is_anomalous ? '#ef4444' : '#3b82f6')
                }
                opacity={entry.is_weekend ? 0.8 : 1}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-gray-600 mt-1 text-center">
        Estimated from monthly claim volumes and business day counts
      </p>
    </div>
  )
}

function MonthlyTrendChart({ data, meanPaid }: {
  data: TemporalAnalysis['monthly_trend']
  meanPaid: number
}) {
  if (!data || data.length === 0) return null

  const chartData = data.map(d => ({
    ...d,
    month_short: d.month.length >= 7 ? d.month.slice(2, 7) : d.month,
  }))

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Monthly Billing Trend with Anomaly Detection
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="month_short"
            tick={{ fill: '#9ca3af', fontSize: 10 }}
            interval={Math.max(0, Math.floor(chartData.length / 12) - 1)}
          />
          <YAxis
            tick={{ fill: '#9ca3af', fontSize: 10 }}
            tickFormatter={(v: number) => fmt(v)}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#e5e7eb' }}
            formatter={(value: number, name: string) => {
              if (name === 'total_paid') return [fmt(value), 'Total Paid']
              return [value, name]
            }}
            labelFormatter={(label: string) => `Month: ${label}`}
          />
          {meanPaid > 0 && (
            <ReferenceLine
              y={meanPaid}
              stroke="#6b7280"
              strokeDasharray="5 5"
              label={{ value: 'Mean', fill: '#6b7280', fontSize: 10, position: 'insideTopRight' }}
            />
          )}
          <Line
            type="monotone"
            dataKey="total_paid"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={(props: { cx: number; cy: number; payload: { is_anomaly: boolean; anomaly_type: string | null; z_score_paid: number } }) => {
              const { cx, cy, payload } = props
              if (!payload.is_anomaly) return <circle key={`dot-${cx}`} cx={cx} cy={cy} r={3} fill="#3b82f6" />
              const color = Math.abs(payload.z_score_paid) >= 3 ? '#ef4444' : '#f97316'
              return (
                <g key={`dot-${cx}`}>
                  <circle cx={cx} cy={cy} r={8} fill={color} opacity={0.3} />
                  <circle cx={cx} cy={cy} r={4} fill={color} stroke="#fff" strokeWidth={1} />
                </g>
              )
            }}
            activeDot={{ r: 6, stroke: '#fff', strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-4 mt-2 justify-center text-[10px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" /> Normal
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-orange-500 inline-block" /> Anomaly (2+ std dev)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Severe (3+ std dev)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 border-t border-dashed border-gray-500 inline-block" /> Mean
        </span>
      </div>
    </div>
  )
}

function AnomalyList({ anomalies }: { anomalies: TemporalAnomaly[] }) {
  if (!anomalies || anomalies.length === 0) {
    return (
      <div className="text-center py-6 text-gray-600 text-sm">
        No temporal anomalies detected for this provider.
      </div>
    )
  }

  const criticalCount = anomalies.filter(a => a.severity === 'CRITICAL').length
  const highCount = anomalies.filter(a => a.severity === 'HIGH').length

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Detected Temporal Anomalies ({anomalies.length})
        </h3>
        <div className="flex items-center gap-2">
          {criticalCount > 0 && (
            <span className="text-[10px] px-2 py-0.5 bg-red-900/40 border border-red-700 rounded-full text-red-300 font-bold">
              {criticalCount} CRITICAL
            </span>
          )}
          {highCount > 0 && (
            <span className="text-[10px] px-2 py-0.5 bg-orange-900/40 border border-orange-700 rounded-full text-orange-300 font-bold">
              {highCount} HIGH
            </span>
          )}
        </div>
      </div>
      <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
        {anomalies.map((anomaly, i) => {
          const s = SEVERITY_COLORS[anomaly.severity] || SEVERITY_COLORS.LOW
          return (
            <div
              key={i}
              className={`border rounded-lg px-4 py-3 ${s.bg} ${s.border}`}
            >
              <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                <SeverityBadge severity={anomaly.severity} />
                <AnomalyTypeBadge type={anomaly.type} />
                <span className="text-[10px] text-gray-500 font-mono ml-auto">
                  {anomaly.date_range}
                </span>
              </div>
              <p className="text-sm text-gray-300 leading-relaxed">
                {anomaly.description}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function TemporalAnalysisSection({ npi }: { npi: string }) {
  const { data, isLoading, error } = useQuery<TemporalAnalysis>({
    queryKey: ['temporal-analysis', npi],
    queryFn: () => api.temporalAnalysis(npi),
    enabled: !!npi,
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Temporal Anomaly Detection</h2>
        <div className="h-40 flex items-center justify-center text-gray-600 text-sm">
          Analyzing temporal patterns...
        </div>
      </div>
    )
  }

  if (error) {
    const errMsg = String(error)
    if (errMsg.includes('404')) return null
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Temporal Anomaly Detection</h2>
        <p className="text-xs text-gray-500">Could not load temporal analysis.</p>
      </div>
    )
  }

  if (!data || data.summary.total_months === 0) return null

  const hasAnomalies = data.detected_anomalies.length > 0
  const hasCritical = (data.summary.critical_count ?? 0) > 0

  return (
    <div className={`card ${
      hasCritical
        ? 'border-red-800 bg-red-950/10'
        : hasAnomalies
          ? 'border-yellow-800/50 bg-yellow-950/5'
          : ''
    }`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-gray-300">Temporal Anomaly Detection</h2>
          {hasCritical && (
            <span className="text-[10px] px-2 py-0.5 bg-red-900 border border-red-700 rounded-full text-red-300 font-bold animate-pulse">
              CRITICAL ANOMALIES
            </span>
          )}
          {!hasCritical && hasAnomalies && (
            <span className="text-[10px] px-2 py-0.5 bg-yellow-900/60 border border-yellow-700 rounded-full text-yellow-300 font-bold">
              {data.detected_anomalies.length} ANOMAL{data.detected_anomalies.length === 1 ? 'Y' : 'IES'}
            </span>
          )}
          {!hasAnomalies && (
            <span className="text-[10px] px-2 py-0.5 bg-green-900/40 border border-green-800 rounded-full text-green-400 font-bold">
              NO ANOMALIES
            </span>
          )}
        </div>
        <div className="text-[10px] text-gray-500">
          {data.summary.total_months} months analyzed
        </div>
      </div>

      {/* Summary stats bar */}
      <div className="flex divide-x divide-gray-800 border border-gray-800 rounded-lg mb-5 bg-gray-900/50">
        {[
          { label: 'Months', value: data.summary.total_months, color: 'text-blue-400' },
          { label: 'Anomalies', value: data.summary.anomaly_count, color: data.summary.anomaly_count > 0 ? 'text-red-400' : 'text-green-400' },
          { label: 'Avg Monthly', value: fmt(data.summary.mean_monthly_paid), color: 'text-gray-300' },
          { label: 'Impossible Days', value: data.impossible_days.length, color: data.impossible_days.length > 0 ? 'text-red-400' : 'text-green-400' },
        ].map(stat => (
          <div key={stat.label} className="flex-1 px-4 py-2.5 text-center">
            <p className="text-[9px] text-gray-500 uppercase tracking-wider">{stat.label}</p>
            <p className={`text-lg font-bold mt-0.5 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-5 mb-5">
        {/* Day of week chart */}
        <DayOfWeekChart data={data.day_of_week_distribution} />

        {/* Monthly trend chart */}
        <MonthlyTrendChart
          data={data.monthly_trend}
          meanPaid={data.summary.mean_monthly_paid}
        />
      </div>

      {/* Anomaly list */}
      <AnomalyList anomalies={data.detected_anomalies} />

      {/* Impossible days detail */}
      {data.impossible_days.length > 0 && (
        <div className="mt-4 border-t border-gray-800 pt-4">
          <h3 className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2">
            Impossible Day Volumes ({data.impossible_days.length})
          </h3>
          <p className="text-[10px] text-gray-500 mb-3">
            Months where estimated daily service hours exceed 24 hours per business day (based on 15 min/claim)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] text-gray-500 border-b border-gray-800">
                  <th className="text-left pb-2 pr-4 font-medium">Month</th>
                  <th className="text-right pb-2 pr-4 font-medium">Claims</th>
                  <th className="text-right pb-2 pr-4 font-medium">Biz Days</th>
                  <th className="text-right pb-2 pr-4 font-medium">Claims/Day</th>
                  <th className="text-right pb-2 pr-4 font-medium">Est. Hours/Day</th>
                  <th className="text-right pb-2 font-medium">Paid</th>
                </tr>
              </thead>
              <tbody>
                {data.impossible_days.map(imp => (
                  <tr key={imp.month} className="border-b border-gray-800/50 text-xs">
                    <td className="py-1.5 pr-4 font-mono text-gray-300">{imp.month}</td>
                    <td className="py-1.5 pr-4 text-right text-gray-400">{imp.total_claims.toLocaleString()}</td>
                    <td className="py-1.5 pr-4 text-right text-gray-500">{imp.business_days}</td>
                    <td className="py-1.5 pr-4 text-right text-orange-400 font-mono">{imp.claims_per_day.toFixed(1)}</td>
                    <td className="py-1.5 pr-4 text-right font-bold text-red-400 font-mono">
                      {imp.estimated_daily_hours.toFixed(1)}h
                    </td>
                    <td className="py-1.5 text-right text-gray-400">{fmt(imp.total_paid)}</td>
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
