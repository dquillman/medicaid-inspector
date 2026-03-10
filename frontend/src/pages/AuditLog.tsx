import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Link } from 'react-router-dom'
import type { AuditLogEntry } from '../lib/types'

const ACTION_TYPES = [
  'scan_started', 'scan_completed', 'provider_viewed', 'review_status_changed',
  'review_assigned', 'report_exported', 'exclusion_checked', 'review_bulk_updated',
  'review_backfilled', 'scan_reset',
]

const ENTITY_TYPES = ['provider', 'review', 'system', 'report', 'alert_rule']

function actionColor(action: string): string {
  if (action.includes('status') || action.includes('assigned') || action.includes('bulk'))
    return 'bg-red-900/40 text-red-300 border-red-800'
  if (action.includes('viewed') || action.includes('checked'))
    return 'bg-blue-900/40 text-blue-300 border-blue-800'
  if (action.includes('scan') || action.includes('reset'))
    return 'bg-green-900/40 text-green-300 border-green-800'
  if (action.includes('export'))
    return 'bg-purple-900/40 text-purple-300 border-purple-800'
  return 'bg-gray-800 text-gray-300 border-gray-700'
}

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleString()
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function EntityLink({ type, id }: { type: string; id: string }) {
  if (type === 'provider' && /^\d{10}$/.test(id)) {
    return <Link to={`/providers/${id}`} className="text-blue-400 hover:underline font-mono">{id}</Link>
  }
  if (type === 'review' && /^\d{10}$/.test(id)) {
    return <Link to={`/review`} className="text-blue-400 hover:underline font-mono">{id}</Link>
  }
  return <span className="font-mono text-gray-300">{id}</span>
}

function DetailsCell({ details }: { details: Record<string, unknown> | null }) {
  if (!details) return <span className="text-gray-600">--</span>
  const entries = Object.entries(details)
  if (entries.length === 0) return <span className="text-gray-600">--</span>
  return (
    <div className="flex flex-wrap gap-1">
      {entries.slice(0, 4).map(([k, v]) => (
        <span key={k} className="text-[11px] bg-gray-800 border border-gray-700 rounded px-1.5 py-0.5">
          <span className="text-gray-500">{k}:</span>{' '}
          <span className="text-gray-300">{String(v)}</span>
        </span>
      ))}
    </div>
  )
}

export default function AuditLog() {
  const [page, setPage] = useState(1)
  const [actionFilter, setActionFilter] = useState('')
  const [entityFilter, setEntityFilter] = useState('')
  const limit = 30

  const { data, isLoading } = useQuery({
    queryKey: ['audit-log', page, actionFilter, entityFilter],
    queryFn: () => api.auditLog({
      page,
      limit,
      action_type: actionFilter || undefined,
      entity_type: entityFilter || undefined,
    }),
    refetchInterval: 10_000,
  })

  const { data: stats } = useQuery({
    queryKey: ['audit-stats'],
    queryFn: () => api.auditStats(),
    staleTime: 30_000,
  })

  const entries: AuditLogEntry[] = data?.entries ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / limit)

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">Audit Log</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          System-wide activity trail -- {total} total entries
        </p>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="card">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Total Events</p>
            <p className="text-2xl font-bold text-white mt-1">{stats.total_entries.toLocaleString()}</p>
          </div>
          <div className="card">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Action Types</p>
            <p className="text-2xl font-bold text-white mt-1">{Object.keys(stats.by_action_type).length}</p>
          </div>
          <div className="card">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Active Days</p>
            <p className="text-2xl font-bold text-white mt-1">{stats.actions_per_day.length}</p>
          </div>
          <div className="card">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Top Entity</p>
            <p className="text-sm font-mono text-white mt-1 truncate">
              {stats.most_active_entities[0]?.entity ?? '--'}
            </p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <select
          value={actionFilter}
          onChange={e => { setActionFilter(e.target.value); setPage(1) }}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:border-blue-500 outline-none"
        >
          <option value="">All Actions</option>
          {ACTION_TYPES.map(a => (
            <option key={a} value={a}>{formatAction(a)}</option>
          ))}
        </select>

        <select
          value={entityFilter}
          onChange={e => { setEntityFilter(e.target.value); setPage(1) }}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:border-blue-500 outline-none"
        >
          <option value="">All Entities</option>
          {ENTITY_TYPES.map(e => (
            <option key={e} value={e}>{e.charAt(0).toUpperCase() + e.slice(1)}</option>
          ))}
        </select>

        {(actionFilter || entityFilter) && (
          <button
            onClick={() => { setActionFilter(''); setEntityFilter(''); setPage(1) }}
            className="text-xs text-gray-500 hover:text-white transition-colors"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500">Loading audit log...</div>
        ) : entries.length === 0 ? (
          <div className="p-8 text-center text-gray-500">No audit entries found</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-[10px] text-gray-500 uppercase tracking-wider">
                <th className="px-4 py-2.5">Timestamp</th>
                <th className="px-4 py-2.5">Action</th>
                <th className="px-4 py-2.5">Entity</th>
                <th className="px-4 py-2.5">Details</th>
                <th className="px-4 py-2.5">User</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(entry => (
                <tr key={entry.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-2.5 text-gray-400 whitespace-nowrap text-xs font-mono">
                    {formatTimestamp(entry.timestamp)}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-block text-[11px] px-2 py-0.5 rounded border ${actionColor(entry.action_type)}`}>
                      {formatAction(entry.action_type)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-xs text-gray-500 mr-1">{entry.entity_type}/</span>
                    <EntityLink type={entry.entity_type} id={entry.entity_id} />
                  </td>
                  <td className="px-4 py-2.5">
                    <DetailsCell details={entry.details} />
                  </td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{entry.user}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">
            Page {page} of {totalPages} ({total} entries)
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="btn-ghost disabled:opacity-30"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="btn-ghost disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
