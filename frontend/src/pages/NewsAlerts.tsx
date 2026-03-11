import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { NewsAlert } from '../lib/types'

const CATEGORY_COLORS: Record<string, string> = {
  news: 'bg-blue-900/60 text-blue-300 border-blue-700',
  legal: 'bg-yellow-900/60 text-yellow-300 border-yellow-700',
  enforcement: 'bg-red-900/60 text-red-300 border-red-700',
  settlement: 'bg-green-900/60 text-green-300 border-green-700',
}

const SEVERITY_COLORS: Record<string, string> = {
  low: 'text-gray-400',
  medium: 'text-yellow-400',
  high: 'text-orange-400',
  critical: 'text-red-400',
}

const SEVERITY_DOTS: Record<string, string> = {
  low: 'bg-gray-500',
  medium: 'bg-yellow-500',
  high: 'bg-orange-500',
  critical: 'bg-red-500',
}

const CATEGORIES = ['', 'news', 'legal', 'enforcement', 'settlement']
const SEVERITIES = ['', 'low', 'medium', 'high', 'critical']

export default function NewsAlerts() {
  const qc = useQueryClient()
  const [catFilter, setCatFilter] = useState('')
  const [sevFilter, setSevFilter] = useState('')
  const [searchText, setSearchText] = useState('')
  const [showForm, setShowForm] = useState(false)

  // Form state
  const [form, setForm] = useState({
    title: '',
    source: '',
    url: '',
    category: 'news',
    summary: '',
    severity: 'medium',
    npi: '',
    date: '',
  })

  const { data, isLoading } = useQuery({
    queryKey: ['news-alerts', catFilter, sevFilter, searchText],
    queryFn: () =>
      api.newsAlerts({
        category: catFilter || undefined,
        severity: sevFilter || undefined,
        search: searchText || undefined,
      }),
    refetchInterval: 60_000,
  })

  const createMut = useMutation({
    mutationFn: (d: typeof form) => api.createNewsAlert({
      ...d,
      npi: d.npi || undefined,
      date: d.date || undefined,
      severity: d.severity || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['news-alerts'] })
      setShowForm(false)
      setForm({ title: '', source: '', url: '', category: 'news', summary: '', severity: 'medium', npi: '', date: '' })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteNewsAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['news-alerts'] }),
  })

  const scanMut = useMutation({
    mutationFn: () => api.scanHhsNews(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['news-alerts'] }),
  })

  const alerts = data?.alerts ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">News & Legal Alerts</h1>
          <p className="text-sm text-gray-500 mt-1">
            Track enforcement actions, legal proceedings, settlements, and industry news
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending}
            className="btn-ghost text-sm"
          >
            {scanMut.isPending ? 'Scanning...' : 'Scan HHS OIG'}
          </button>
          <button
            onClick={() => setShowForm(!showForm)}
            className="btn-primary text-sm"
          >
            {showForm ? 'Cancel' : '+ Add Alert'}
          </button>
        </div>
      </div>

      {/* Scan result message */}
      {scanMut.data && (
        <div className={`text-sm px-4 py-2 rounded border ${scanMut.data.ok ? 'bg-green-950/40 border-green-800 text-green-300' : 'bg-red-950/40 border-red-800 text-red-300'}`}>
          {scanMut.data.message}
        </div>
      )}

      {/* Add form */}
      {showForm && (
        <div className="card space-y-3">
          <h2 className="text-sm font-semibold text-gray-300">Add New Alert</h2>
          <div className="grid grid-cols-2 gap-3">
            <input
              className="input"
              placeholder="Title *"
              value={form.title}
              onChange={e => setForm({ ...form, title: e.target.value })}
            />
            <input
              className="input"
              placeholder="Source (e.g. DOJ, HHS OIG)"
              value={form.source}
              onChange={e => setForm({ ...form, source: e.target.value })}
            />
            <input
              className="input"
              placeholder="URL *"
              value={form.url}
              onChange={e => setForm({ ...form, url: e.target.value })}
            />
            <input
              className="input"
              placeholder="NPI (optional)"
              value={form.npi}
              onChange={e => setForm({ ...form, npi: e.target.value })}
            />
            <select
              className="input"
              value={form.category}
              onChange={e => setForm({ ...form, category: e.target.value })}
            >
              <option value="news">News</option>
              <option value="legal">Legal</option>
              <option value="enforcement">Enforcement</option>
              <option value="settlement">Settlement</option>
            </select>
            <select
              className="input"
              value={form.severity}
              onChange={e => setForm({ ...form, severity: e.target.value })}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
            <input
              className="input"
              type="date"
              placeholder="Date"
              value={form.date}
              onChange={e => setForm({ ...form, date: e.target.value })}
            />
          </div>
          <textarea
            className="input w-full"
            placeholder="Summary *"
            rows={3}
            value={form.summary}
            onChange={e => setForm({ ...form, summary: e.target.value })}
          />
          <button
            className="btn-primary text-sm"
            disabled={!form.title || !form.url || !form.summary || createMut.isPending}
            onClick={() => createMut.mutate(form)}
          >
            {createMut.isPending ? 'Saving...' : 'Save Alert'}
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 items-center flex-wrap">
        <input
          className="input w-64"
          placeholder="Search alerts..."
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
        />
        <select
          className="input"
          value={catFilter}
          onChange={e => setCatFilter(e.target.value)}
        >
          <option value="">All Categories</option>
          {CATEGORIES.filter(Boolean).map(c => (
            <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
          ))}
        </select>
        <select
          className="input"
          value={sevFilter}
          onChange={e => setSevFilter(e.target.value)}
        >
          <option value="">All Severities</option>
          {SEVERITIES.filter(Boolean).map(s => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
        <span className="text-xs text-gray-500 ml-auto">
          {alerts.length} alert{alerts.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Alert cards */}
      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading alerts...</div>
      ) : alerts.length === 0 ? (
        <div className="text-center py-12 text-gray-600">
          No alerts found. Add alerts manually or scan HHS OIG for enforcement actions.
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert: NewsAlert) => (
            <div key={alert.id} className="card flex gap-4 items-start">
              {/* Severity dot */}
              <div className="pt-1">
                <div className={`w-3 h-3 rounded-full ${SEVERITY_DOTS[alert.severity] || 'bg-gray-500'}`} title={alert.severity} />
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded border ${CATEGORY_COLORS[alert.category] || 'bg-gray-800 text-gray-400 border-gray-700'}`}>
                    {alert.category}
                  </span>
                  <span className={`text-xs font-medium ${SEVERITY_COLORS[alert.severity] || 'text-gray-400'}`}>
                    {alert.severity}
                  </span>
                  <span className="text-xs text-gray-600">{alert.date}</span>
                  {alert.npi && (
                    <a href={`/providers/${alert.npi}`} className="text-xs text-blue-400 hover:underline">
                      NPI: {alert.npi}
                    </a>
                  )}
                </div>

                <a
                  href={alert.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-semibold text-white hover:text-blue-300 transition-colors"
                >
                  {alert.title}
                </a>

                <p className="text-xs text-gray-400 mt-1 line-clamp-2">{alert.summary}</p>

                <div className="flex items-center gap-3 mt-2 text-xs text-gray-600">
                  <span>Source: {alert.source}</span>
                  <a
                    href={alert.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-500 hover:text-blue-400"
                  >
                    View source
                  </a>
                </div>
              </div>

              {/* Delete button */}
              <button
                onClick={() => {
                  if (confirm('Delete this alert?')) deleteMut.mutate(alert.id)
                }}
                className="text-gray-600 hover:text-red-400 transition-colors shrink-0"
                title="Delete alert"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
