import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import type { WatchlistEntry } from '../lib/types'
import { fmt } from '../lib/format'

function riskColor(score: number | null) {
  if (score == null) return 'text-gray-500'
  if (score >= 70) return 'text-red-400'
  if (score >= 50) return 'text-orange-400'
  if (score >= 30) return 'text-yellow-400'
  return 'text-green-400'
}

function AddDialog({ onClose }: { onClose: () => void }) {
  const [npi, setNpi] = useState('')
  const [reason, setReason] = useState('')
  const [threshold, setThreshold] = useState(50)
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const queryClient = useQueryClient()

  const addMutation = useMutation({
    mutationFn: () => api.addToWatchlist({ npi, reason, alert_threshold: threshold, notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      onClose()
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md shadow-2xl" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-4">Add Provider to Watchlist</h3>
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">NPI</label>
            <input
              type="text"
              value={npi}
              onChange={e => setNpi(e.target.value)}
              placeholder="Enter provider NPI"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Reason</label>
            <input
              type="text"
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="Why are you watching this provider?"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Alert Threshold (risk score)</label>
            <input
              type="number"
              value={threshold}
              onChange={e => setThreshold(Number(e.target.value))}
              min={0}
              max={100}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Notes</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Optional notes..."
              rows={2}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:border-blue-500 focus:outline-none resize-none"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors">Cancel</button>
          <button
            onClick={() => addMutation.mutate()}
            disabled={!npi.trim() || addMutation.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded transition-colors"
          >
            {addMutation.isPending ? 'Adding...' : 'Add to Watchlist'}
          </button>
        </div>
      </div>
    </div>
  )
}

function InlineNoteEditor({ entry }: { entry: WatchlistEntry }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(entry.notes)
  const queryClient = useQueryClient()

  const updateMutation = useMutation({
    mutationFn: () => api.updateWatchlist(entry.npi, { notes: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      setEditing(false)
    },
  })

  if (!editing) {
    return (
      <span
        className="text-gray-400 text-xs cursor-pointer hover:text-gray-200 transition-colors"
        onClick={() => setEditing(true)}
        title="Click to edit"
      >
        {entry.notes || '(click to add note)'}
      </span>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="text"
        value={value}
        onChange={e => setValue(e.target.value)}
        autoFocus
        onKeyDown={e => {
          if (e.key === 'Enter') updateMutation.mutate()
          if (e.key === 'Escape') { setEditing(false); setValue(entry.notes) }
        }}
        className="px-2 py-0.5 bg-gray-800 border border-gray-600 rounded text-white text-xs w-48 focus:outline-none focus:border-blue-500"
      />
      <button
        onClick={() => updateMutation.mutate()}
        className="text-green-400 hover:text-green-300 text-xs"
        disabled={updateMutation.isPending}
      >
        Save
      </button>
    </div>
  )
}

export default function Watchlist() {
  const [showAdd, setShowAdd] = useState(false)
  const [filter, setFilter] = useState<'all' | 'active' | 'alerts'>('all')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => api.watchlist(),
    refetchInterval: 30_000,
  })

  const removeMutation = useMutation({
    mutationFn: (npi: string) => api.removeFromWatchlist(npi),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  const toggleActiveMutation = useMutation({
    mutationFn: ({ npi, active }: { npi: string; active: boolean }) =>
      api.updateWatchlist(npi, { active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  const items = data?.items ?? []
  const filtered = items.filter(item => {
    if (filter === 'active') return item.active
    if (filter === 'alerts') return item.in_alert
    return true
  })

  const alertCount = data?.alert_count ?? 0
  const activeCount = items.filter(i => i.active).length

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Provider Watchlist</h1>
          <p className="text-sm text-gray-500 mt-1">
            Monitor specific providers and get alerts when their risk scores exceed thresholds
          </p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded transition-colors flex items-center gap-2"
        >
          + Add Provider
        </button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card text-center">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Total Watched</p>
          <p className="text-2xl font-bold text-blue-400 mt-1">{items.length}</p>
        </div>
        <div className="card text-center">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Active</p>
          <p className="text-2xl font-bold text-green-400 mt-1">{activeCount}</p>
        </div>
        <div className="card text-center">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Alerts Triggered</p>
          <p className={`text-2xl font-bold mt-1 ${alertCount > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {alertCount}
          </p>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1">
        {([
          { key: 'all', label: `All (${items.length})` },
          { key: 'active', label: `Active (${activeCount})` },
          { key: 'alerts', label: `Alerts (${alertCount})` },
        ] as const).map(tab => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`px-4 py-2 text-sm rounded transition-colors ${
              filter === tab.key
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-gray-500">Loading watchlist...</div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-12 text-gray-500">
          {items.length === 0
            ? 'No providers on watchlist yet. Click "Add Provider" to get started.'
            : 'No providers match the current filter.'}
        </div>
      ) : (
        <div className="card p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-[10px] uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">NPI</th>
                <th className="px-4 py-3">Specialty</th>
                <th className="px-4 py-3 text-right">Risk Score</th>
                <th className="px-4 py-3 text-right">Threshold</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Reason</th>
                <th className="px-4 py-3">Notes</th>
                <th className="px-4 py-3">Added</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(entry => (
                <tr
                  key={entry.npi}
                  className={`border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors ${
                    entry.in_alert ? 'bg-red-950/20' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <Link to={`/providers/${entry.npi}`} className="text-blue-400 hover:text-blue-300 font-medium">
                      {entry.name || 'Unknown'}
                    </Link>
                    {entry.state && (
                      <span className="text-gray-600 text-xs ml-2">{entry.city ? `${entry.city}, ` : ''}{entry.state}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-gray-400 text-xs">{entry.npi}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">{entry.specialty || '--'}</td>
                  <td className={`px-4 py-3 text-right font-bold ${riskColor(entry.risk_score)}`}>
                    {entry.risk_score != null ? entry.risk_score.toFixed(1) : '--'}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-400">{entry.alert_threshold}</td>
                  <td className="px-4 py-3">
                    {entry.in_alert ? (
                      <span className="px-2 py-0.5 bg-red-900/50 border border-red-700 rounded-full text-red-400 text-xs font-medium">
                        ALERT
                      </span>
                    ) : entry.active ? (
                      <span className="px-2 py-0.5 bg-green-900/40 border border-green-800 rounded-full text-green-400 text-xs">
                        Active
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 bg-gray-800 border border-gray-700 rounded-full text-gray-500 text-xs">
                        Paused
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs max-w-[150px] truncate" title={entry.reason}>
                    {entry.reason || '--'}
                  </td>
                  <td className="px-4 py-3">
                    <InlineNoteEditor entry={entry} />
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                    {new Date(entry.added_date * 1000).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => toggleActiveMutation.mutate({ npi: entry.npi, active: !entry.active })}
                        className="px-2 py-1 text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 rounded transition-colors"
                        title={entry.active ? 'Pause monitoring' : 'Resume monitoring'}
                      >
                        {entry.active ? 'Pause' : 'Resume'}
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Remove ${entry.name || entry.npi} from watchlist?`)) {
                            removeMutation.mutate(entry.npi)
                          }
                        }}
                        className="px-2 py-1 text-xs text-red-400 hover:text-red-300 bg-gray-800 hover:bg-red-900/30 rounded transition-colors"
                        title="Remove from watchlist"
                      >
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && <AddDialog onClose={() => setShowAdd(false)} />}
    </div>
  )
}
