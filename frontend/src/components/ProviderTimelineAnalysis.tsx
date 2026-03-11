import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Line, ReferenceDot,
} from 'recharts'
import { api } from '../lib/api'
import type { TimelineMonth, TimelineEvent } from '../lib/types'
import { fmt } from '../lib/format'

function EventIcon({ type }: { type: string }) {
  switch (type) {
    case 'first_billing':
      return <span className="text-green-400 text-base" title="First billing">&#9654;</span>
    case 'last_billing':
      return <span className="text-blue-400 text-base" title="Last billing">&#9632;</span>
    case 'spike':
      return <span className="text-red-400 text-base" title="Billing spike">&#9650;</span>
    case 'gap':
      return <span className="text-yellow-400 text-base" title="Billing gap">&#9888;</span>
    default:
      return <span className="text-gray-400 text-base">&#8226;</span>
  }
}

function eventColor(type: string) {
  switch (type) {
    case 'first_billing': return 'border-green-800 bg-green-950/30'
    case 'last_billing': return 'border-blue-800 bg-blue-950/30'
    case 'spike': return 'border-red-800 bg-red-950/30'
    case 'gap': return 'border-yellow-800 bg-yellow-950/30'
    default: return 'border-gray-800 bg-gray-900'
  }
}

function eventLabel(type: string) {
  switch (type) {
    case 'first_billing': return 'FIRST ACTIVITY'
    case 'last_billing': return 'LAST ACTIVITY'
    case 'spike': return 'BILLING SPIKE'
    case 'gap': return 'BILLING GAP'
    default: return type.toUpperCase()
  }
}

interface CustomDotProps {
  cx?: number
  cy?: number
  payload?: TimelineMonth
}

function SpikeDot({ cx, cy, payload }: CustomDotProps) {
  if (!payload?.is_spike || cx == null || cy == null) return null
  return (
    <circle
      cx={cx}
      cy={cy}
      r={6}
      fill="#ef4444"
      stroke="#991b1b"
      strokeWidth={2}
      opacity={0.9}
    />
  )
}

export default function ProviderTimelineAnalysis({ npi }: { npi: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['timeline-analysis', npi],
    queryFn: () => api.timelineAnalysis(npi),
    enabled: !!npi,
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="h-64 flex items-center justify-center text-gray-600 text-sm">
        Loading timeline analysis...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="text-red-400 text-sm">
        {String(error ?? 'Failed to load timeline analysis')}
      </div>
    )
  }

  if (!data.months.length) {
    return (
      <div className="text-gray-500 text-sm">
        No billing timeline data available for this provider.
      </div>
    )
  }

  const chartData = data.months.map(m => ({
    ...m,
    month: m.month?.slice(0, 7) ?? '',
  }))

  const spikeMonths = data.months.filter(m => m.is_spike)

  return (
    <div className="space-y-4">
      {/* Summary KPI strip */}
      <div className="flex gap-4 flex-wrap">
        {[
          { label: 'Active Months', value: data.summary.total_months, color: 'text-blue-400' },
          { label: 'Avg Monthly', value: fmt(data.summary.avg_monthly_paid), color: 'text-gray-300' },
          { label: 'Peak Month', value: fmt(data.summary.max_monthly_paid), color: 'text-purple-400' },
          {
            label: 'Spike Months',
            value: data.summary.spike_count,
            color: data.summary.spike_count > 0 ? 'text-red-400' : 'text-green-400',
          },
          {
            label: 'Billing Gaps',
            value: data.summary.gap_count,
            color: data.summary.gap_count > 0 ? 'text-yellow-400' : 'text-green-400',
          },
        ].map(kpi => (
          <div key={kpi.label} className="bg-gray-800/50 border border-gray-700 rounded-lg px-4 py-2 text-center min-w-[100px]">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{kpi.label}</p>
            <p className={`text-lg font-bold mt-0.5 ${kpi.color}`}>{kpi.value}</p>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div>
        <p className="text-[11px] text-gray-500 mb-2">
          Monthly billing with spike detection (red dots = billing &gt; 2x provider average)
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
            <defs>
              <linearGradient id="gradPaidTimeline" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="month"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              yAxisId="paid"
              tickFormatter={fmt}
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              yAxisId="count"
              orientation="right"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                background: '#111827',
                border: '1px solid #374151',
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: '#e5e7eb', fontWeight: 'bold' }}
              formatter={(v: number, name: string) => {
                switch (name) {
                  case 'total_paid': return [fmt(v), 'Total Paid']
                  case 'claim_count': return [v.toLocaleString(), 'Claims']
                  case 'unique_beneficiaries': return [v.toLocaleString(), 'Beneficiaries']
                  case 'unique_hcpcs_count': return [v.toLocaleString(), 'Unique HCPCS']
                  default: return [v, name]
                }
              }}
            />
            <Legend
              formatter={(v) => {
                switch (v) {
                  case 'total_paid': return 'Total Paid'
                  case 'claim_count': return 'Claims'
                  case 'unique_beneficiaries': return 'Beneficiaries'
                  default: return v
                }
              }}
            />
            <Area
              yAxisId="paid"
              type="monotone"
              dataKey="total_paid"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#gradPaidTimeline)"
              dot={<SpikeDot />}
              activeDot={{ r: 5, strokeWidth: 1 }}
            />
            <Line
              yAxisId="count"
              type="monotone"
              dataKey="claim_count"
              stroke="#10b981"
              strokeWidth={1.5}
              dot={false}
            />
            <Line
              yAxisId="count"
              type="monotone"
              dataKey="unique_beneficiaries"
              stroke="#f59e0b"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="4 2"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Notable Events */}
      {data.events.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Notable Events ({data.events.length})
          </h3>
          <div className="space-y-1.5">
            {data.events.map((event, i) => (
              <div
                key={`${event.type}-${event.month}-${i}`}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${eventColor(event.type)}`}
              >
                <EventIcon type={event.type} />
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500 min-w-[100px]">
                  {eventLabel(event.type)}
                </span>
                <span className="font-mono text-xs text-gray-400 min-w-[70px]">
                  {event.month?.slice(0, 7)}
                </span>
                <span className="text-sm text-gray-300 flex-1">
                  {event.description}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
