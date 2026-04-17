import { useState, useRef, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ReviewItem, ReviewCounts, AuditEntry } from '../lib/types'
import { fmt } from '../lib/format'
import EmptyState from '../components/EmptyState'

type StatusFilter = 'all' | 'pending' | 'assigned' | 'investigating' | 'confirmed_fraud' | 'referred' | 'dismissed'

const STATUS_LABELS: Record<string, string> = {
  pending:         'Pending',
  assigned:        'Assigned',
  investigating:   'Investigating',
  confirmed_fraud: 'Confirmed Fraud',
  referred:        'Referred',
  dismissed:       'Dismissed',
}

const STATUS_COLORS: Record<string, string> = {
  pending:         'text-yellow-400 bg-yellow-400/10',
  assigned:        'text-cyan-400 bg-cyan-400/10',
  investigating:   'text-purple-400 bg-purple-400/10',
  confirmed_fraud: 'text-red-400 bg-red-400/10',
  referred:        'text-orange-400 bg-orange-400/10',
  dismissed:       'text-gray-500 bg-gray-500/10',
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

function AssignedToCell({ item, onSave }: { item: ReviewItem; onSave: (assignedTo: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.assigned_to ?? '')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { setValue(item.assigned_to ?? '') }, [item.assigned_to])

  const handleClick = () => {
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const handleBlur = () => {
    setEditing(false)
    if (value !== (item.assigned_to ?? '')) onSave(value)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); inputRef.current?.blur() }
    if (e.key === 'Escape') { setValue(item.assigned_to ?? ''); setEditing(false) }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        placeholder="Name..."
        className="w-full bg-gray-800 text-gray-200 text-xs rounded px-2 py-1 border border-cyan-600 focus:outline-none"
      />
    )
  }

  return (
    <button
      onClick={handleClick}
      className="text-left text-xs text-gray-500 hover:text-gray-300 transition-colors truncate max-w-[120px] block"
      title={item.assigned_to || 'Click to assign'}
    >
      {item.assigned_to || <span className="italic">Assign...</span>}
    </button>
  )
}

function formatTimestamp(ts: number) {
  if (!ts) return '--'
  const d = new Date(ts * 1000)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

function AuditTrailPanel({ npi }: { npi: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['review-history', npi],
    queryFn: () => api.getReviewHistory(npi),
  })

  if (isLoading) return <div className="text-xs text-gray-500 py-2 px-4">Loading history...</div>

  const trail: AuditEntry[] = data?.audit_trail ?? []
  if (trail.length === 0) return <div className="text-xs text-gray-600 py-2 px-4 italic">No history yet</div>

  return (
    <div className="px-4 py-2 max-h-48 overflow-y-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-600 border-b border-gray-800">
            <th className="text-left py-1 pr-3">Time</th>
            <th className="text-left py-1 pr-3">Action</th>
            <th className="text-left py-1 pr-3">From</th>
            <th className="text-left py-1 pr-3">To</th>
            <th className="text-left py-1">Note</th>
          </tr>
        </thead>
        <tbody>
          {trail.slice().reverse().map((entry, i) => (
            // Audit-trail entries don't carry a server-assigned id, so build
            // a stable composite key from timestamp + action + prev/new status.
            // Falling back to index only when all identifying fields are blank.
            <tr
              key={`${entry.timestamp ?? ''}-${entry.action ?? ''}-${entry.previous_status ?? ''}-${entry.new_status ?? ''}-${i}`}
              className="border-b border-gray-800/50"
            >
              <td className="py-1 pr-3 text-gray-500 whitespace-nowrap">{formatTimestamp(entry.timestamp)}</td>
              <td className="py-1 pr-3 text-gray-400">{entry.action === 'status_change' ? 'Status' : 'Assignment'}</td>
              <td className="py-1 pr-3">
                <span className={`px-1.5 py-0.5 rounded ${STATUS_COLORS[entry.previous_status] ?? 'text-gray-500'}`}>
                  {STATUS_LABELS[entry.previous_status] ?? entry.previous_status}
                </span>
              </td>
              <td className="py-1 pr-3">
                <span className={`px-1.5 py-0.5 rounded ${STATUS_COLORS[entry.new_status] ?? 'text-gray-500'}`}>
                  {STATUS_LABELS[entry.new_status] ?? entry.new_status}
                </span>
              </td>
              <td className="py-1 text-gray-500 max-w-[200px] truncate" title={entry.note}>{entry.note || '--'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatusDropdown({ item, onChange }: { item: ReviewItem; onChange: (status: string) => void }) {
  return (
    <select
      value={item.status}
      onChange={e => onChange(e.target.value)}
      className="bg-gray-800 text-xs rounded px-1.5 py-1 border border-gray-700 text-gray-300 focus:outline-none focus:border-blue-500 cursor-pointer"
    >
      {Object.entries(STATUS_LABELS).map(([key, label]) => (
        <option key={key} value={key}>{label}</option>
      ))}
    </select>
  )
}

function ReviewRow({
  item,
  selected,
  expanded,
  rowIndex,
  onToggleSelect,
  onToggleExpand,
  onStatusChange,
  onNotesSave,
  onAssignedToSave,
}: {
  item: ReviewItem
  selected: boolean
  expanded: boolean
  rowIndex: number
  onToggleSelect: (npi: string) => void
  onToggleExpand: (npi: string) => void
  onStatusChange: (npi: string, status: string) => void
  onNotesSave: (npi: string, notes: string) => void
  onAssignedToSave: (npi: string, assignedTo: string) => void
}) {
  const isFraud = item.status === 'confirmed_fraud'
  return (
    <>
      <tr className={`border-b border-gray-800 hover:bg-gray-800/40 transition-colors ${
        selected ? 'bg-blue-900/20' : isFraud ? 'bg-red-950/20' : rowIndex % 2 === 1 ? 'bg-gray-900/30' : ''
      } ${isFraud ? 'row-fraud' : ''}`}>
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
            className="text-blue-400 hover:text-blue-300 font-mono-data text-sm underline underline-offset-2"
          >
            {item.npi}
          </Link>
        </td>
        <td className="px-4 py-3 text-sm text-gray-300 max-w-[160px] truncate" title={item.provider_name}>
          {item.provider_name || <span className="text-gray-600 italic">--</span>}
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{item.state || '--'}</td>
        <td className="px-4 py-3">
          <RiskBadge score={item.risk_score} />
        </td>
        <td className="px-4 py-3 text-sm text-gray-300">
          {item.flags.length > 0 ? (
            <span className="text-red-400 font-medium">{item.flags.length} flag{item.flags.length !== 1 ? 's' : ''}</span>
          ) : (
            <span className="text-gray-600">--</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-gray-400">{fmt(item.total_paid)}</td>
        <td className="px-4 py-3">
          <StatusDropdown item={item} onChange={status => onStatusChange(item.npi, status)} />
        </td>
        <td className="px-4 py-3">
          <AssignedToCell item={item} onSave={assignedTo => onAssignedToSave(item.npi, assignedTo)} />
        </td>
        <td className="px-4 py-3">
          <NotesCell item={item} onSave={notes => onNotesSave(item.npi, notes)} />
        </td>
        <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
          {formatTimestamp(item.updated_at)}
        </td>
        <td className="px-4 py-3">
          <button
            onClick={() => onToggleExpand(item.npi)}
            title="View audit history"
            className={`px-2 py-1 text-xs rounded transition-colors ${
              expanded
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200'
            }`}
          >
            {expanded ? 'Hide' : 'History'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-900/50">
          <td colSpan={12} className="p-0">
            <AuditTrailPanel npi={item.npi} />
          </td>
        </tr>
      )}
    </>
  )
}

function StatusTab({
  label,
  count,
  active,
  onClick,
  variant = 'default',
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
  variant?: 'default' | 'danger'
}) {
  const isDanger = variant === 'danger'
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded transition-colors flex items-center gap-2 ${
        active
          ? isDanger
            ? 'bg-red-700 text-white border border-red-500'
            : 'bg-blue-600 text-white'
          : isDanger
            ? 'bg-red-950 text-red-400 border border-red-800 hover:bg-red-900 hover:text-red-300'
            : 'bg-gray-800 text-gray-400 hover:text-gray-200 hover:bg-gray-700'
      }`}
    >
      {isDanger && '\u26A0 '}{label}
      <span className={`text-xs px-1.5 py-0.5 rounded-full font-bold ${
        active
          ? isDanger ? 'bg-red-500' : 'bg-blue-500'
          : isDanger ? 'bg-red-800' : 'bg-gray-700'
      }`}>
        {count}
      </span>
    </button>
  )
}

type SortField = 'npi' | 'provider_name' | 'state' | 'risk_score' | 'flags' | 'total_paid' | 'status' | 'updated_at'
type SortDir = 'asc' | 'desc'

function SortHeader({ label, field, sortField, sortDir, onSort }: {
  label: string
  field: SortField
  sortField: SortField
  sortDir: SortDir
  onSort: (f: SortField) => void
}) {
  const active = sortField === field
  return (
    <th
      className="px-4 py-3 cursor-pointer hover:text-gray-300 select-none transition-colors"
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          <span className="text-blue-400">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>
        ) : (
          <span className="text-gray-700">\u25BC</span>
        )}
      </span>
    </th>
  )
}

export default function ReviewQueue() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const statusParam = searchParams.get('status') as StatusFilter | null
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(statusParam ?? 'all')
  const [page, setPage] = useState(1)
  const [selectedNpis, setSelectedNpis] = useState<Set<string>>(new Set())
  const [npiSearch, setNpiSearch] = useState('')
  const [sortField, setSortField] = useState<SortField>('risk_score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const LIMIT = 50

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir(field === 'risk_score' || field === 'total_paid' || field === 'flags' || field === 'updated_at' ? 'desc' : 'asc')
    }
  }

  const { data: countsData } = useQuery({
    queryKey: ['review-counts'],
    queryFn: api.reviewCounts,
    refetchInterval: 10000,
  })


  const counts: ReviewCounts = countsData ?? {
    pending: 0, assigned: 0, investigating: 0, confirmed_fraud: 0, referred: 0, dismissed: 0, total: 0,
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

  const [expandedNpis, setExpandedNpis] = useState<Set<string>>(new Set())

  const updateMutation = useMutation({
    mutationFn: ({ npi, update }: { npi: string; update: { status?: string; notes?: string; assigned_to?: string | null } }) =>
      api.updateReview(npi, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-counts'] })
      queryClient.invalidateQueries({ queryKey: ['review-history'] })
    },
  })

  const bulkMutation = useMutation({
    mutationFn: (data: { npis: string[]; status: string }) =>
      api.bulkUpdateReview(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-counts'] })
      queryClient.invalidateQueries({ queryKey: ['review-history'] })
      setSelectedNpis(new Set())
    },
  })

  const handleStatusChange = (npi: string, status: string) =>
    updateMutation.mutate({ npi, update: { status } })

  const handleNotesSave = (npi: string, notes: string) =>
    updateMutation.mutate({ npi, update: { notes } })

  const handleAssignedToSave = (npi: string, assignedTo: string) =>
    updateMutation.mutate({ npi, update: { assigned_to: assignedTo || null } })

  const handleToggleExpand = (npi: string) => {
    setExpandedNpis(prev => {
      const next = new Set(prev)
      next.has(npi) ? next.delete(npi) : next.add(npi)
      return next
    })
  }

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

  const rawItems   = data?.items ?? []

  // NPI search filter (client-side on current page data)
  const searchFiltered = npiSearch.trim()
    ? rawItems.filter(i => i.npi.includes(npiSearch.trim()))
    : rawItems

  // Client-side sort
  const sortedItems = [...searchFiltered].sort((a, b) => {
    let cmp = 0
    switch (sortField) {
      case 'npi':           cmp = a.npi.localeCompare(b.npi); break
      case 'provider_name': cmp = (a.provider_name || '').localeCompare(b.provider_name || ''); break
      case 'state':         cmp = (a.state || '').localeCompare(b.state || ''); break
      case 'risk_score':    cmp = a.risk_score - b.risk_score; break
      case 'flags':         cmp = a.flags.length - b.flags.length; break
      case 'total_paid':    cmp = a.total_paid - b.total_paid; break
      case 'status':        cmp = a.status.localeCompare(b.status); break
      case 'updated_at':    cmp = (a.updated_at || 0) - (b.updated_at || 0); break
    }
    return sortDir === 'asc' ? cmp : -cmp
  })

  const items      = sortedItems
  const total      = npiSearch.trim() ? searchFiltered.length : (data?.total ?? 0)
  const totalPages = npiSearch.trim() ? 1 : Math.ceil((data?.total ?? 0) / LIMIT)
  const allOnPageSelected = items.length > 0 && items.every(i => selectedNpis.has(i.npi))

  const tabs: { key: StatusFilter; label: string; count: number }[] = [
    { key: 'all',             label: 'All',           count: counts.total },
    { key: 'pending',         label: 'Pending',       count: counts.pending },
    { key: 'assigned',        label: 'Assigned',      count: counts.assigned },
    { key: 'investigating',   label: 'Investigating', count: counts.investigating },
    { key: 'confirmed_fraud', label: 'Confirmed',     count: counts.confirmed_fraud },
    { key: 'referred',        label: 'Referred',      count: counts.referred },
    { key: 'dismissed',       label: 'Dismissed',     count: counts.dismissed },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white uppercase tracking-wide">Investigation Queue</h1>
          <p className="text-gray-500 text-xs mt-1 uppercase tracking-wider">
            Flagged Providers Requiring Human Review
          </p>
          <p className="text-xs text-gray-400 mt-2">
            <span className="text-yellow-400 font-semibold">{counts.pending}</span> cases pending review
            <span className="text-gray-600 mx-2">&middot;</span>
            <span className="text-red-400 font-semibold">{counts.confirmed_fraud}</span> confirmed fraud
            <span className="text-gray-600 mx-2">&middot;</span>
            <span className="text-orange-400 font-semibold">{counts.referred}</span> referred to law enforcement
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <input
              type="text"
              value={npiSearch}
              onChange={e => { setNpiSearch(e.target.value); setPage(1) }}
              placeholder="Search NPI..."
              className="w-44 px-3 py-2 pl-8 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:border-blue-500 focus:outline-none font-mono"
            />
            <svg className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {npiSearch && (
              <button
                onClick={() => setNpiSearch('')}
                className="absolute right-2 top-2 text-gray-500 hover:text-gray-300 text-sm"
              >
                x
              </button>
            )}
          </div>
          <button
            onClick={() => window.open('/api/review/export/csv', '_blank', 'noopener,noreferrer')}
            className="px-4 py-2 text-sm rounded transition-colors border font-medium flex items-center gap-2 bg-gray-700 hover:bg-gray-600 text-gray-200 border-gray-600"
            aria-label="Export full review queue as CSV"
          >
            Export All CSV
          </button>
          <button
            onClick={handleExportCSV}
            className={`px-4 py-2 text-sm rounded transition-colors border font-medium flex items-center gap-2 ${
              statusFilter === 'confirmed_fraud'
                ? 'bg-red-700 hover:bg-red-600 text-white border-red-500 shadow-lg shadow-red-900/30'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-200 border-gray-600'
            }`}
            aria-label="Export confirmed fraud cases as CSV"
          >
            {statusFilter === 'confirmed_fraud' && <span>&#8659;</span>}
            Export Confirmed CSV
          </button>
        </div>
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
            variant={tab.key === 'confirmed_fraud' ? 'danger' : 'default'}
          />
        ))}
      </div>

      {/* Bulk action bar */}
      {selectedNpis.size > 0 && (
        <div className="flex items-center gap-4 px-5 py-3 bg-blue-950/60 border-2 border-blue-600 rounded-lg shadow-lg">
          <span className="text-sm text-blue-200 font-bold uppercase tracking-wider">
            {selectedNpis.size} Selected
          </span>
          <div className="flex gap-2 ml-2">
            <button
              onClick={() => handleBulkAction('confirmed_fraud')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-red-700 hover:bg-red-600 text-white font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
            >
              Confirm Fraud
            </button>
            <button
              onClick={() => handleBulkAction('dismissed')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-gray-600 hover:bg-gray-500 text-white font-medium transition-colors disabled:opacity-50"
            >
              Dismiss All
            </button>
            <button
              onClick={() => handleBulkAction('reviewed')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white font-medium transition-colors disabled:opacity-50"
            >
              Mark Reviewed
            </button>
            <button
              onClick={() => handleBulkAction('referred')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-orange-700 hover:bg-orange-600 text-white font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
            >
              Refer to MFCU
            </button>
          </div>
          <button
            onClick={() => setSelectedNpis(new Set())}
            className="ml-auto text-xs text-gray-400 hover:text-gray-200"
          >
            Clear selection
          </button>
        </div>
      )}

      {/* Table */}
      <div className="card p-0 overflow-x-auto">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500 text-sm">Loading…</div>
        ) : items.length === 0 ? (
          <EmptyState
            variant="no-results"
            title="No items in this queue"
            description="Providers flagged for review will appear here."
          />
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
                <SortHeader label="NPI" field="npi" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Name" field="provider_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="St" field="state" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Risk" field="risk_score" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Signals" field="flags" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Total Paid" field="total_paid" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Status" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3">Assigned To</th>
                <th className="px-4 py-3">Notes</th>
                <SortHeader label="Last Updated" field="updated_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3">Audit</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => (
                <ReviewRow
                  key={item.npi}
                  item={item}
                  rowIndex={idx}
                  selected={selectedNpis.has(item.npi)}
                  expanded={expandedNpis.has(item.npi)}
                  onToggleSelect={handleToggleSelect}
                  onToggleExpand={handleToggleExpand}
                  onStatusChange={handleStatusChange}
                  onNotesSave={handleNotesSave}
                  onAssignedToSave={handleAssignedToSave}
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

      {/* MFCU Referral Status Panel */}
      <ReferralStatusPanel />
    </div>
  )
}

function ReferralStatusPanel() {
  const { data: refData } = useQuery({
    queryKey: ['referral-stats'],
    queryFn: api.referralStats,
    refetchInterval: 30000,
  })
  const { data: listData } = useQuery({
    queryKey: ['referrals-list'],
    queryFn: () => api.listReferrals(),
    refetchInterval: 30000,
  })

  const stats = refData
  const referrals = listData?.referrals ?? []

  const STAGE_LABELS: Record<string, string> = {
    draft: 'Draft',
    submitted: 'Submitted',
    acknowledged: 'Acknowledged',
    under_investigation: 'Under Investigation',
    outcome_received: 'Outcome Received',
  }
  const STAGE_COLORS: Record<string, string> = {
    draft: 'text-gray-400 bg-gray-700',
    submitted: 'text-orange-400 bg-orange-900/40',
    acknowledged: 'text-blue-400 bg-blue-900/40',
    under_investigation: 'text-purple-400 bg-purple-900/40',
    outcome_received: 'text-green-400 bg-green-900/40',
  }

  if (!stats && referrals.length === 0) return null

  return (
    <div className="card p-5">
      <h2 className="text-lg font-bold text-white uppercase tracking-wide mb-4">MFCU Referral Tracker</h2>

      {stats && stats.total_referrals > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-orange-400">{stats.total_referrals}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Total Referrals</div>
          </div>
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-blue-400">{stats.unique_providers}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Unique Providers</div>
          </div>
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-purple-400">{stats.by_stage?.under_investigation ?? 0}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Under Investigation</div>
          </div>
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-green-400">{stats.by_stage?.outcome_received ?? 0}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Outcomes Received</div>
          </div>
        </div>
      )}

      {referrals.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-500 uppercase tracking-wider">
                <th className="px-3 py-2">Ref #</th>
                <th className="px-3 py-2">NPI</th>
                <th className="px-3 py-2">Provider</th>
                <th className="px-3 py-2">Stage</th>
                <th className="px-3 py-2">Jurisdiction</th>
                <th className="px-3 py-2">Submitted</th>
                <th className="px-3 py-2">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {referrals.slice(0, 10).map(ref => (
                <tr key={ref.id} className="border-b border-gray-800 hover:bg-gray-800/40">
                  <td className="px-3 py-2 text-xs font-mono text-orange-400">{ref.referral_id}</td>
                  <td className="px-3 py-2">
                    <Link to={`/providers/${ref.npi}`} className="text-blue-400 hover:text-blue-300 text-xs font-mono underline">
                      {ref.npi}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-gray-300 text-xs truncate max-w-[160px]">{ref.provider_name || '--'}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded ${STAGE_COLORS[ref.stage] ?? 'text-gray-400 bg-gray-700'}`}>
                      {STAGE_LABELS[ref.stage] ?? ref.stage}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500">{ref.jurisdiction || '--'}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {ref.referral_date ? new Date(ref.referral_date * 1000).toLocaleDateString() : '--'}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {ref.outcome ? (
                      <span className="text-green-400">{ref.outcome.replace('_', ' ')}</span>
                    ) : (
                      <span className="text-gray-600">Pending</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-500 text-sm">No MFCU referrals yet. Use "Refer to MFCU" on confirmed fraud cases.</p>
      )}
    </div>
  )
}
