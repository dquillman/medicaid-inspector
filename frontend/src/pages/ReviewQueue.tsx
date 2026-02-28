import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ReviewItem, ReviewCounts } from '../lib/types'

type StatusFilter = 'all' | 'pending' | 'reviewed' | 'confirmed_fraud' | 'dismissed'

const STATUS_LABELS: Record<string, string> = {
  pending:        'Pending',
  reviewed:       'Reviewed',
  confirmed_fraud:'Confirmed Fraud',
  dismissed:      'Dismissed',
}

const STATUS_COLORS: Record<string, string> = {
  pending:        'text-yellow-400 bg-yellow-400/10',
  reviewed:       'text-blue-400 bg-blue-400/10',
  confirmed_fraud:'text-red-400 bg-red-400/10',
  dismissed:      'text-gray-500 bg-gray-500/10',
}

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v}`
}

function RiskBadge({ score }: { score: number }) {
  const color =
    score >= 75 ? 'bg-red-900 text-red-300' :
    score >= 50 ? 'bg-orange-900 text-orange-300' :
    'bg-yellow-900 text-yellow-300'
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${color}`}>
      {score.toFixed(1)}
    </span>
  )
}

function NotesCell({ item, onSave }: { item: ReviewItem; onSave: (notes: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.notes)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { setValue(item.notes) }, [item.notes])

  const handleClick = () => {
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const handleBlur = () => {
    setEditing(false)
    if (value !== item.notes) onSave(value)
  }

  if (editing) {
    return (
      <textarea
        ref={inputRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={handleBlur}
        className="w-full bg-gray-800 text-gray-200 text-xs rounded px-2 py-1 border border-blue-600 focus:outline-none resize-none"
        rows={2}
      />
    )
  }

  return (
    <button
      onClick={handleClick}
      className="text-left text-xs text-gray-500 hover:text-gray-300 transition-colors truncate max-w-[180px] block"
      title={item.notes || 'Click to add notes'}
    >
      {item.notes || <span className="italic">Add notes…</span>}
    </button>
  )
}

function ReviewRow({
  item,
  selected,
  onToggleSelect,
  onStatusChange,
  onNotesSave,
}: {
  item: ReviewItem
  selected: boolean
  onToggleSelect: (npi: string) => void
  onStatusChange: (npi: string, status: string) => void
  onNotesSave: (npi: string, notes: string) => void
}) {
  return (
    <tr className={`border-b border-gray-800 hover:bg-gray-800/40 transition-colors ${selected ? 'bg-blue-900/20' : ''}`}>
      <td className="px-3 py-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(item.npi)}
          className="accent-blue-500 cursor-pointer"
        />
      </td>
      <td className="px-4 py-3">
        <Link
          to={`/providers/${item.npi}`}
          className="text-blue-400 hover:text-blue-300 font-mono text-sm underline underline-offset-2"
        >
          {item.npi}
        </Link>
      </td>
      <td className="px-4 py-3 text-sm text-gray-300 max-w-[160px] truncate" title={item.provider_name}>
        {item.provider_name || <span className="text-gray-600 italic">—</span>}
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">{item.state || '—'}</td>
      <td className="px-4 py-3">
        <RiskBadge score={item.risk_score} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-300">
        {item.flags.length > 0 ? (
          <span className="text-red-400 font-medium">{item.flags.length} flag{item.flags.length !== 1 ? 's' : ''}</span>
        ) : (
          <span className="text-gray-600">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-sm text-gray-400">{fmt(item.total_paid)}</td>
      <td className="px-4 py-3">
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[item.status] ?? 'text-gray-400'}`}>
          {STATUS_LABELS[item.status] ?? item.status}
        </span>
      </td>
      <td className="px-4 py-3">
        <NotesCell item={item} onSave={notes => onNotesSave(item.npi, notes)} />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-1">
          <button
            onClick={() => onStatusChange(item.npi, 'confirmed_fraud')}
            disabled={item.status === 'confirmed_fraud'}
            title="Confirm Fraud"
            className="px-2 py-1 text-xs rounded bg-red-900 hover:bg-red-700 text-red-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Confirm
          </button>
          <button
            onClick={() => onStatusChange(item.npi, 'dismissed')}
            disabled={item.status === 'dismissed'}
            title="Dismiss"
            className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Dismiss
          </button>
          <button
            onClick={() => onStatusChange(item.npi, 'reviewed')}
            disabled={item.status === 'reviewed'}
            title="Mark Reviewed"
            className="px-2 py-1 text-xs rounded bg-blue-900 hover:bg-blue-700 text-blue-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Review
          </button>
        </div>
      </td>
    </tr>
  )
}

function StatusTab({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded transition-colors flex items-center gap-2 ${
        active
          ? 'bg-blue-600 text-white'
          : 'bg-gray-800 text-gray-400 hover:text-gray-200 hover:bg-gray-700'
      }`}
    >
      {label}
      <span className={`text-xs px-1.5 py-0.5 rounded-full ${active ? 'bg-blue-500' : 'bg-gray-700'}`}>
        {count}
      </span>
    </button>
  )
}

export default function ReviewQueue() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(1)
  const [selectedNpis, setSelectedNpis] = useState<Set<string>>(new Set())
  const LIMIT = 50

  const { data: countsData } = useQuery({
    queryKey: ['review-counts'],
    queryFn: api.reviewCounts,
    refetchInterval: 10000,
  })

  // Auto-backfill once if queue is empty but prescan cache has data
  const hasBackfilled = useRef(false)
  useEffect(() => {
    if (!hasBackfilled.current && countsData && countsData.total === 0) {
      hasBackfilled.current = true
      api.reviewBackfill().then(() => {
        queryClient.invalidateQueries({ queryKey: ['review-counts'] })
        queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      })
    }
  }, [countsData, queryClient])

  const counts: ReviewCounts = countsData ?? {
    pending: 0, reviewed: 0, confirmed_fraud: 0, dismissed: 0, total: 0,
  }

  const { data, isLoading } = useQuery({
    queryKey: ['review-queue', statusFilter, page],
    queryFn: () => api.reviewQueue({
      status: statusFilter === 'all' ? undefined : statusFilter,
      page,
      limit: LIMIT,
    }),
    refetchInterval: 15000,
  })

  // Clear selection when page/filter changes
  useEffect(() => { setSelectedNpis(new Set()) }, [statusFilter, page])

  const updateMutation = useMutation({
    mutationFn: ({ npi, update }: { npi: string; update: { status?: string; notes?: string } }) =>
      api.updateReview(npi, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-counts'] })
    },
  })

  const bulkMutation = useMutation({
    mutationFn: (data: { npis: string[]; status: string }) =>
      api.bulkUpdateReview(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-counts'] })
      setSelectedNpis(new Set())
    },
  })

  const handleStatusChange = (npi: string, status: string) =>
    updateMutation.mutate({ npi, update: { status } })

  const handleNotesSave = (npi: string, notes: string) =>
    updateMutation.mutate({ npi, update: { notes } })

  const handleToggleSelect = (npi: string) => {
    setSelectedNpis(prev => {
      const next = new Set(prev)
      next.has(npi) ? next.delete(npi) : next.add(npi)
      return next
    })
  }

  const handleSelectAll = () => {
    const allNpis = items.map(i => i.npi)
    const allSelected = allNpis.every(n => selectedNpis.has(n))
    if (allSelected) {
      setSelectedNpis(new Set())
    } else {
      setSelectedNpis(new Set(allNpis))
    }
  }

  const handleBulkAction = (status: string) => {
    const npis = Array.from(selectedNpis)
    if (npis.length === 0) return
    bulkMutation.mutate({ npis, status })
  }

  const handleExportCSV = () => {
    const confirmed = items.filter(i => i.status === 'confirmed_fraud')
    if (confirmed.length === 0) {
      alert('No confirmed fraud cases on this page to export. Switch to the Confirmed tab first.')
      return
    }
    const headers = ['NPI', 'Name', 'State', 'Risk Score', 'Flags', 'Total Paid', 'Total Claims', 'Status', 'Notes']
    const rows = confirmed.map(i => [
      i.npi,
      `"${(i.provider_name ?? '').replace(/"/g, '""')}"`,
      i.state ?? '',
      i.risk_score.toFixed(1),
      i.flags.length.toString(),
      i.total_paid.toString(),
      i.total_claims.toString(),
      i.status,
      `"${(i.notes ?? '').replace(/"/g, '""')}"`,
    ])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `confirmed_fraud_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const items      = data?.items ?? []
  const total      = data?.total ?? 0
  const totalPages = Math.ceil(total / LIMIT)
  const allOnPageSelected = items.length > 0 && items.every(i => selectedNpis.has(i.npi))

  const tabs: { key: StatusFilter; label: string; count: number }[] = [
    { key: 'all',            label: 'All',       count: counts.total },
    { key: 'pending',        label: 'Pending',   count: counts.pending },
    { key: 'confirmed_fraud',label: 'Confirmed', count: counts.confirmed_fraud },
    { key: 'reviewed',       label: 'Reviewed',  count: counts.reviewed },
    { key: 'dismissed',      label: 'Dismissed', count: counts.dismissed },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Review Queue</h1>
          <p className="text-gray-400 text-sm mt-1">
            Potential fraud cases flagged during scan
          </p>
        </div>
        <button
          onClick={handleExportCSV}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm rounded transition-colors border border-gray-600"
        >
          Export Confirmed CSV
        </button>
      </div>

      {/* Status tabs */}
      <div className="flex gap-2 flex-wrap">
        {tabs.map(tab => (
          <StatusTab
            key={tab.key}
            label={tab.label}
            count={tab.count}
            active={statusFilter === tab.key}
            onClick={() => { setStatusFilter(tab.key); setPage(1) }}
          />
        ))}
      </div>

      {/* Bulk action bar */}
      {selectedNpis.size > 0 && (
        <div className="flex items-center gap-3 px-4 py-2.5 bg-blue-900/30 border border-blue-700 rounded-lg">
          <span className="text-sm text-blue-300 font-medium">
            {selectedNpis.size} selected
          </span>
          <div className="flex gap-2 ml-2">
            <button
              onClick={() => handleBulkAction('confirmed_fraud')}
              disabled={bulkMutation.isPending}
              className="px-3 py-1 text-xs rounded bg-red-800 hover:bg-red-700 text-red-200 transition-colors disabled:opacity-50"
            >
              Confirm All
            </button>
            <button
              onClick={() => handleBulkAction('dismissed')}
              disabled={bulkMutation.isPending}
              className="px-3 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors disabled:opacity-50"
            >
              Dismiss All
            </button>
            <button
              onClick={() => handleBulkAction('reviewed')}
              disabled={bulkMutation.isPending}
              className="px-3 py-1 text-xs rounded bg-blue-800 hover:bg-blue-700 text-blue-200 transition-colors disabled:opacity-50"
            >
              Mark Reviewed
            </button>
          </div>
          <button
            onClick={() => setSelectedNpis(new Set())}
            className="ml-auto text-xs text-gray-500 hover:text-gray-300"
          >
            Clear selection
          </button>
        </div>
      )}

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500 text-sm">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-gray-500 text-sm">
            {counts.total === 0
              ? 'No flagged providers yet — run a scan to populate the queue.'
              : 'No items match this filter.'}
          </div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-500 uppercase tracking-wider">
                <th className="px-3 py-3">
                  <input
                    type="checkbox"
                    checked={allOnPageSelected}
                    onChange={handleSelectAll}
                    className="accent-blue-500 cursor-pointer"
                    title="Select all on page"
                  />
                </th>
                <th className="px-4 py-3">NPI</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">St</th>
                <th className="px-4 py-3">Risk</th>
                <th className="px-4 py-3">Signals</th>
                <th className="px-4 py-3">Total Paid</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Notes</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <ReviewRow
                  key={item.npi}
                  item={item}
                  selected={selectedNpis.has(item.npi)}
                  onToggleSelect={handleToggleSelect}
                  onStatusChange={handleStatusChange}
                  onNotesSave={handleNotesSave}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span>{total.toLocaleString()} total items</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 bg-gray-800 rounded disabled:opacity-40 hover:bg-gray-700 transition-colors"
            >
              Prev
            </button>
            <span className="px-3 py-1">Page {page} of {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 bg-gray-800 rounded disabled:opacity-40 hover:bg-gray-700 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
