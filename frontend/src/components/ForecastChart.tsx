import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import type { TimelineRow, BillingForecast } from '../lib/types'
import { fmt } from '../lib/format'

interface Props {
  timeline: TimelineRow[]
  forecast: BillingForecast
}

interface ChartRow {
  month: string
  actual_paid?: number
  predicted_paid?: number
  lower_bound?: number
  upper_bound?: number
  band?: [number, number]
}

export default function ForecastChart({ timeline, forecast }: Props) {
  if (!forecast.forecasted_months.length) {
    return (
      <p className="text-xs text-gray-500 italic">
        Not enough data to generate a forecast (minimum 3 months required).
      </p>
    )
  }

  // Build combined chart data
  const rows: ChartRow[] = []

  // Actual data
  for (const row of timeline) {
    rows.push({
      month: row.month?.slice(0, 7) ?? '',
      actual_paid: row.total_paid,
    })
  }

  // Bridge: last actual month also gets the predicted line start
  if (rows.length > 0) {
    const last = rows[rows.length - 1]
    last.predicted_paid = last.actual_paid
  }

  // Forecast data
  for (const fc of forecast.forecasted_months) {
    rows.push({
      month: fc.month,
      predicted_paid: fc.predicted_paid,
      lower_bound: fc.lower_bound,
      upper_bound: fc.upper_bound,
      band: [fc.lower_bound, fc.upper_bound],
    })
  }

  // Find the boundary month for the reference line
  const boundaryMonth = timeline.length > 0
    ? timeline[timeline.length - 1].month?.slice(0, 7)
    : undefined

  return (
    <div>
      <div className="flex items-center gap-3 mb-2">
        <p className="text-[11px] text-gray-500">
          3-month billing forecast with prediction interval
        </p>
        {forecast.spike_detected && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-900/60 text-red-300 border border-red-700">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            Billing Spike Detected ({forecast.spike_magnitude}x upper bound)
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={rows} margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
          <defs>
            <linearGradient id="gradForecastBand" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.05} />
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
            tickFormatter={fmt}
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#e5e7eb' }}
            formatter={(v: number | [number, number], name: string) => {
              if (name === 'band') {
                const arr = v as [number, number]
                return [`${fmt(arr[0])} – ${fmt(arr[1])}`, 'Prediction Interval']
              }
              return [fmt(v as number),
                name === 'actual_paid' ? 'Actual Paid' : 'Forecast']
            }}
          />
          <Legend
            formatter={(v) =>
              v === 'actual_paid' ? 'Actual Paid' :
              v === 'predicted_paid' ? 'Forecast' :
              v === 'band' ? 'Prediction Interval' : v
            }
          />
          {/* Prediction band */}
          <Area
            type="monotone"
            dataKey="band"
            stroke="none"
            fill="url(#gradForecastBand)"
            connectNulls={false}
            legendType="square"
          />
          {/* Actual line */}
          <Line
            type="monotone"
            dataKey="actual_paid"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />
          {/* Forecast line (dashed) */}
          <Line
            type="monotone"
            dataKey="predicted_paid"
            stroke="#a78bfa"
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={false}
            connectNulls={false}
          />
          {/* Vertical line at boundary */}
          {boundaryMonth && (
            <ReferenceLine
              x={boundaryMonth}
              stroke="#6b7280"
              strokeDasharray="3 3"
              label={{ value: 'Now', fill: '#9ca3af', fontSize: 10, position: 'top' }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
