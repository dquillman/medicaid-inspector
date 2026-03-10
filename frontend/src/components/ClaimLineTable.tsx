import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ClaimLine, HcpcsDetailResponse } from '../lib/types'

function fmt(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(2)}`
}

type SortKey = 'month' | 'hcpcs_code' | 'claims' | 'beneficiaries' | 'paid' | 'servicing_npi'

interface Props {
  npi: string
  initialHcpcsCode?: string
}

function HcpcsDetailPanel({ npi, code, onClose }: { npi: string; code: string; onClose: () => void }) {
  const { data, isLoading } = useQuery<HcpcsDetailResponse>({
    queryKey: ['hcpcs-detail', npi, code],
    queryFn: () => api.hcpcsDetail(npi, code),
  })

  if (isLoading) return <div className="text-gray-500 text-sm py-4">Loading detail for {code}...</div>
  if (!data) return null

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold text-white">
            <span className="font-mono text-blue-400">{data.hcpcs_code}</span>
            {data.description && <span className="text-gray-400 font-normal ml-2">{data.description}</span>}
          </h3>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xs">Close</button>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {[
          { label: 'Total Paid', value: fmt(data.total_paid), color: 'text-green-400' },
          { label: '% of Provider Total', value: `${data.pct_of_total.toFixed(1)}%`, color: 'text-blue-400' },
          { label: 'Avg Paid/Month', value: fmt(data.avg_paid_per_month), color: 'text-yellow-400' },
          { label: 'Active Months', value: String(data.month_count), color: 'text-purple-400' },
        ].map(s => (
          <div key={s.label} className="bg-gray-900/50 rounded px-3 py-2">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider">{s.label}</div>
            <div className={`text-sm font-bold ${s.color}`}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Monthly breakdown table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-700">
              <th className="text-left pb-1.5 pr-3 font-medium">Month</th>
              <th className="text-right pb-1.5 pr-3 font-medium">Claims</th>
              <th className="text-right pb-1.5 pr-3 font-medium">Beneficiaries</th>
              <th className="text-right pb-1.5 pr-3 font-medium">Paid</th>
              <th className="text-left pb-1.5 font-medium">Servicing NPI</th>
            </tr>
          </thead>
          <tbody>
            {data.monthly.map((row, i) => (
              <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="py-1.5 pr-3 font-mono text-gray-300">{row.month}</td>
                <td className="py-1.5 pr-3 text-right text-white">{row.claims.toLocaleString()}</td>
                <td className="py-1.5 pr-3 text-right text-gray-400">{row.beneficiaries.toLocaleString()}</td>
                <td className="py-1.5 pr-3 text-right text-green-400 font-medium">{fmt(row.paid)}</td>
                <td className={`py-1.5 font-mono text-xs ${row.servicing_npi !== npi ? 'text-orange-400' : 'text-gray-500'}`}>
                  {row.servicing_npi}
                  {row.servicing_npi !== npi && <span className="ml-1 text-[9px] text-orange-500/70">(different)</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ClaimLineTable({ npi, initialHcpcsCode }: Props) {
  const [page, setPage] = useState(1)
  const [hcpcsFilter, setHcpcsFilter] = useState(initialHcpcsCode ?? '')
  const [monthFilter, setMonthFilter] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('month')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [detailCode, setDetailCode] = useState<string | null>(null)
  const limit = 50

  const { data, isLoading } = useQuery({
    queryKey: ['claim-lines', npi, hcpcsFilter, monthFilter, page],
    queryFn: () => api.claimLines(npi, {
      hcpcs_code: hcpcsFilter || undefined,
      month: monthFilter || undefined,
      page,
      limit,
    }),
  })

  const rows = data?.claim_lines ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / limit)

  // Client-side sort (within page)
  const sorted = [...rows].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1
    const av = a[sortKey]
    const bv = b[sortKey]
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av).localeCompare(String(bv)) * dir
  })

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir(key === 'month' || key === 'paid' ? 'desc' : 'asc')
    }
  }

  function SortHeader({ k, label, align = 'left' }: { k: SortKey; label: string; align?: 'left' | 'right' }) {
    const arrow = sortKey === k ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : ''
    return (
      <th
        className={`pb-1.5 pr-3 font-medium cursor-pointer hover:text-gray-300 transition-colors text-${align}`}
        onClick={() => toggleSort(k)}
      >
        {label}{arrow}
      </th>
    )
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-3">
        <input
          type="text"
          placeholder="Filter by HCPCS code..."
          value={hcpcsFilter}
          onChange={e => { setHcpcsFilter(e.target.value); setPage(1) }}
          className="bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-xs text-white placeholder-gray-500 w-40 focus:outline-none focus:border-blue-500"
        />
        <input
          type="text"
          placeholder="Filter by month (YYYY-MM)..."
          value={monthFilter}
          onChange={e => { setMonthFilter(e.target.value); setPage(1) }}
          className="bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-xs text-white placeholder-gray-500 w-48 focus:outline-none focus:border-blue-500"
        />
        {(hcpcsFilter || monthFilter) && (
          <button
            onClick={() => { setHcpcsFilter(''); setMonthFilter(''); setPage(1) }}
            className="text-xs text-gray-500 hover:text-gray-300 px-2"
          >
            Clear filters
          </button>
        )}
        <div className="ml-auto text-xs text-gray-500 self-center">
          {total.toLocaleString()} record{total !== 1 ? 's' : ''}
        </div>
      </div>

      {/* HCPCS Detail Panel */}
      {detailCode && (
        <HcpcsDetailPanel npi={npi} code={detailCode} onClose={() => setDetailCode(null)} />
      )}

      {/* Table */}
      {isLoading ? (
        <div className="h-40 flex items-center justify-center text-gray-600 text-sm">Loading claim lines...</div>
      ) : rows.length === 0 ? (
        <div className="h-24 flex items-center justify-center text-gray-600 text-sm">No claim lines found</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700">
                <SortHeader k="month" label="Month" />
                <SortHeader k="hcpcs_code" label="HCPCS Code" />
                <SortHeader k="claims" label="Claims" align="right" />
                <SortHeader k="beneficiaries" label="Beneficiaries" align="right" />
                <SortHeader k="paid" label="Amount Paid" align="right" />
                <SortHeader k="servicing_npi" label="Servicing NPI" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((row: ClaimLine, i: number) => {
                const npiMismatch = row.servicing_npi !== row.billing_npi
                return (
                  <tr
                    key={i}
                    className={`border-b border-gray-800/50 hover:bg-gray-800/30 ${npiMismatch ? 'bg-orange-950/10' : ''}`}
                  >
                    <td className="py-1.5 pr-3 font-mono text-gray-300">
                      <button
                        onClick={() => { setMonthFilter(row.month); setPage(1) }}
                        className="hover:text-blue-400 transition-colors"
                      >
                        {row.month}
                      </button>
                    </td>
                    <td className="py-1.5 pr-3">
                      <button
                        onClick={() => setDetailCode(row.hcpcs_code)}
                        className="font-mono text-blue-400 hover:text-blue-300 hover:underline transition-colors"
                      >
                        {row.hcpcs_code}
                      </button>
                    </td>
                    <td className="py-1.5 pr-3 text-right text-white">{row.claims.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right text-gray-400">{row.beneficiaries.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right text-green-400 font-medium">{fmt(row.paid)}</td>
                    <td className={`py-1.5 font-mono text-xs ${npiMismatch ? 'text-orange-400' : 'text-gray-500'}`}>
                      {row.servicing_npi}
                      {npiMismatch && <span className="ml-1 text-[9px] text-orange-500/70">(mismatch)</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-800">
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            className="text-xs px-3 py-1.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-xs text-gray-500">
            Page {page} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            className="text-xs px-3 py-1.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
