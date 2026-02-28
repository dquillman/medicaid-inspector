import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import type { TimelineRow } from '../lib/types'

interface Props {
  data: TimelineRow[]
}

function fmt(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

export default function SpendingTimeline({ data }: Props) {
  const chartData = data.map(row => ({
    ...row,
    month: row.month?.slice(0, 7) ?? '',
  }))

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={chartData} margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
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
          formatter={(v: number, name: string) => [
            name === 'total_paid' ? fmt(v) : v.toLocaleString(),
            name === 'total_paid' ? 'Total Paid' : name === 'total_claims' ? 'Claims' : 'Beneficiaries',
          ]}
        />
        <Legend
          formatter={(v) =>
            v === 'total_paid' ? 'Total Paid' :
            v === 'total_claims' ? 'Claims' : 'Beneficiaries'
          }
        />
        <Line type="monotone" dataKey="total_paid"               stroke="#3b82f6" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="total_claims"             stroke="#10b981" strokeWidth={1.5} dot={false} />
        <Line type="monotone" dataKey="total_unique_beneficiaries" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}
