import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import type { HcpcsRow } from '../lib/types'

const COLORS = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#f97316','#84cc16']

interface Props {
  data: HcpcsRow[]
}

function fmt(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

export default function HcpcsBreakdown({ data }: Props) {
  const top8       = data.slice(0, 8)
  const grandTotal = top8.reduce((s, r) => s + r.total_paid, 0)
  const pieData    = top8.map(r => ({ name: r.hcpcs_code, value: r.total_paid, description: r.description ?? '' }))

  function PieTooltip({ active, payload }: any) {
    if (!active || !payload?.length) return null
    const { name: code, value, description, fill } = payload[0]?.payload ?? {}
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg shadow-xl px-3 py-2.5 max-w-[240px]">
        <div className="flex items-center gap-2 mb-1">
          <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: fill }} />
          <span className="font-mono font-bold text-white text-sm">{code}</span>
        </div>
        {description
          ? <p className="text-gray-300 text-xs mb-2 leading-snug">{description}</p>
          : <p className="text-gray-600 text-xs italic mb-2">No description available</p>
        }
        <div className="text-blue-400 font-bold text-sm">{fmt(value)}</div>
        <div className="text-gray-500 text-xs">
          {grandTotal > 0 ? ((value / grandTotal) * 100).toFixed(1) : 0}% of total billing
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Pie chart */}
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={80}
            label={false}
          >
            {pieData.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<PieTooltip />} />
        </PieChart>
      </ResponsiveContainer>

      {/* Code list */}
      <div className="space-y-2.5">
        {top8.map((row, i) => {
          const pct = grandTotal > 0 ? ((row.total_paid / grandTotal) * 100).toFixed(0) : '0'
          return (
            <div key={row.hcpcs_code} className="flex items-start gap-2 text-xs">
              <span
                className="w-2.5 h-2.5 rounded-sm flex-shrink-0 mt-0.5"
                style={{ background: COLORS[i % COLORS.length] }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-mono text-white font-bold">{row.hcpcs_code}</span>
                  {row.description
                    ? <span className="text-gray-300">{row.description}</span>
                    : <span className="text-gray-600 italic">no description available</span>
                  }
                </div>
                <div className="mt-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(row.total_paid / (top8[0]?.total_paid || 1)) * 100}%`,
                      background: COLORS[i % COLORS.length],
                    }}
                  />
                </div>
              </div>
              <div className="flex-shrink-0 text-right ml-2">
                <div className="text-white font-semibold">{fmt(row.total_paid)}</div>
                <div className="text-gray-500">{pct}%</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
