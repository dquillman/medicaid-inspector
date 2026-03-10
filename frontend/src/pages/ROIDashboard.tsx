import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api } from '../lib/api'

const RECOVERY_TYPES = [
  { value: 'overpayment', label: 'Overpayment Recovery' },
  { value: 'settlement', label: 'Settlement' },
  { value: 'penalty', label: 'Penalty / Fine' },
  { value: 'voluntary_refund', label: 'Voluntary Refund' },
]

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function rateColor(rate: number): string {
  if (rate > 0.5) return 'text-green-400'
  if (rate > 0.25) return 'text-yellow-400'
  return 'text-red-400'
}

function rateBg(rate: number): string {
  if (rate > 0.5) return 'border-green-800 bg-green-950/20'
  if (rate > 0.25) return 'border-yellow-800 bg-yellow-950/20'
  return 'border-red-800 bg-red-950/20'
}

export default function ROIDashboard() {
  const queryClient = useQueryClient()

  const { data: summary, isLoading } = useQuery({
    queryKey: ['roi-summary'],
    queryFn: api.roiSummary,
    refetchInterval: 10000,
  })

  const { data: recoveriesData } = useQuery({
    queryKey: ['roi-recoveries'],
    queryFn: () => api.roiRecoveries({ page: 1, limit: 50 }),
    refetchInterval: 10000,
  })

  // Provider search for autocomplete
  const [searchQ, setSearchQ] = useState('')
  const { data: searchResults } = useQuery({
    queryKey: ['provider-search', searchQ],
    queryFn: () => api.searchProviders(searchQ),
    enabled: searchQ.length >= 2,
  })

  // Form state
  const [formNpi, setFormNpi] = useState('')
  const [formAmount, setFormAmount] = useState('')
  const [formType, setFormType] = useState('overpayment')
  const [formNotes, setFormNotes] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [formError, setFormError] = useState('')

  const logMutation = useMutation({
    mutationFn: api.logRecovery,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roi-summary'] })
      queryClient.invalidateQueries({ queryKey: ['roi-recoveries'] })
      setFormNpi('')
      setFormAmount('')
      setFormType('overpayment')
      setFormNotes('')
      setSearchQ('')
      setFormError('')
    },
    onError: (err: Error) => {
      setFormError(err.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: api.deleteRecovery,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roi-summary'] })
      queryClient.invalidateQueries({ queryKey: ['roi-recoveries'] })
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const amount = parseFloat(formAmount)
    if (!formNpi || isNaN(amount) || amount <= 0) {
      setFormError('NPI and a positive amount are required')
      return
    }
    logMutation.mutate({
      npi: formNpi,
      amount,
      recovery_type: formType,
      notes: formNotes,
    })
  }

  const recoveryRate = summary?.recovery_rate ?? 0
  const falsePositiveRate = summary?.false_positive_rate ?? 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white uppercase tracking-wide">
          ROI Tracking Dashboard
        </h1>
        <p className="text-gray-500 text-xs mt-1 uppercase tracking-wider">
          Recovery metrics, case outcomes, and return on investigation
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        <div className="card border-green-800 bg-green-950/20 py-4 text-center">
          <p className="text-green-600 text-xs font-bold uppercase tracking-widest mb-1">Total Recovered</p>
          <p className={`text-3xl font-black text-green-400 ${isLoading ? 'animate-pulse' : ''}`}>
            {isLoading ? '...' : fmt(summary?.total_recovered ?? 0)}
          </p>
        </div>

        <div className="card py-4 text-center">
          <p className="text-gray-600 text-xs font-bold uppercase tracking-widest mb-1">Flagged Billing</p>
          <p className={`text-3xl font-black text-blue-400 ${isLoading ? 'animate-pulse' : ''}`}>
            {isLoading ? '...' : fmt(summary?.total_flagged_billing ?? 0)}
          </p>
          <p className="text-gray-600 text-[10px] mt-1">Confirmed + Referred</p>
        </div>

        <div className={`card py-4 text-center ${rateBg(recoveryRate)}`}>
          <p className="text-gray-500 text-xs font-bold uppercase tracking-widest mb-1">Recovery Rate</p>
          <p className={`text-3xl font-black ${rateColor(recoveryRate)} ${isLoading ? 'animate-pulse' : ''}`}>
            {isLoading ? '...' : `${(recoveryRate * 100).toFixed(1)}%`}
          </p>
        </div>

        <div className="card py-4 text-center">
          <p className="text-gray-600 text-xs font-bold uppercase tracking-widest mb-1">Cases Confirmed</p>
          <p className={`text-3xl font-black text-red-400 ${isLoading ? 'animate-pulse' : ''}`}>
            {isLoading ? '...' : (summary?.cases_confirmed ?? 0).toLocaleString()}
          </p>
          <p className="text-gray-600 text-[10px] mt-1">
            + {summary?.cases_referred ?? 0} referred
          </p>
        </div>

        <div className={`card py-4 text-center ${rateBg(1 - falsePositiveRate)}`}>
          <p className="text-gray-500 text-xs font-bold uppercase tracking-widest mb-1">False Positive Rate</p>
          <p className={`text-3xl font-black ${rateColor(1 - falsePositiveRate)} ${isLoading ? 'animate-pulse' : ''}`}>
            {isLoading ? '...' : `${(falsePositiveRate * 100).toFixed(1)}%`}
          </p>
          <p className="text-gray-600 text-[10px] mt-1">
            {summary?.cases_dismissed ?? 0} dismissed
          </p>
        </div>
      </div>

      {/* Secondary KPIs */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card py-3">
          <p className="text-gray-600 text-xs uppercase tracking-wider">Avg Time to Resolution</p>
          <p className="text-2xl font-bold mt-1 text-gray-300">
            {isLoading ? '...' : `${(summary?.avg_time_to_resolution ?? 0).toFixed(1)} days`}
          </p>
        </div>
        <div className="card py-3">
          <p className="text-gray-600 text-xs uppercase tracking-wider">Total Recoveries Logged</p>
          <p className="text-2xl font-bold mt-1 text-gray-300">
            {recoveriesData?.total ?? 0}
          </p>
        </div>
        <div className="card py-3">
          <p className="text-gray-600 text-xs uppercase tracking-wider">Cases Resolved</p>
          <p className="text-2xl font-bold mt-1 text-gray-300">
            {(summary?.cases_confirmed ?? 0) + (summary?.cases_referred ?? 0) + (summary?.cases_dismissed ?? 0)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Monthly Trend Chart */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Monthly Recovery Trend</h2>
          {(summary?.monthly_trend ?? []).length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={summary!.monthly_trend} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="month"
                  tick={{ fill: '#9ca3af', fontSize: 11 }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#9ca3af', fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={(v: number) => fmt(v)}
                />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                  formatter={(v: number) => [fmt(v), 'Recovered']}
                />
                <Line
                  type="monotone"
                  dataKey="amount"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={{ fill: '#22c55e', r: 4 }}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-gray-600 text-sm">
              No recovery data yet. Log recoveries to see trends.
            </div>
          )}
        </div>

        {/* Log Recovery Form */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Log Recovery</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* NPI with autocomplete */}
            <div className="relative">
              <label className="block text-xs text-gray-500 mb-1">Provider NPI</label>
              <input
                type="text"
                value={formNpi}
                onChange={e => {
                  setFormNpi(e.target.value)
                  setSearchQ(e.target.value)
                  setShowDropdown(true)
                }}
                onFocus={() => setShowDropdown(true)}
                onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
                placeholder="Enter NPI or search by name"
                className="w-full bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:border-blue-500 focus:outline-none"
              />
              {showDropdown && searchResults && searchResults.length > 0 && (
                <div className="absolute z-10 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                  {searchResults.map((p) => (
                    <button
                      key={p.npi}
                      type="button"
                      className="w-full text-left px-3 py-2 hover:bg-gray-700 text-sm"
                      onMouseDown={() => {
                        setFormNpi(p.npi)
                        setSearchQ('')
                        setShowDropdown(false)
                      }}
                    >
                      <span className="text-white font-mono">{p.npi}</span>
                      {p.name && <span className="text-gray-400 ml-2">{p.name}</span>}
                      {p.state && <span className="text-gray-600 ml-1">({p.state})</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Amount Recovered ($)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={formAmount}
                onChange={e => setFormAmount(e.target.value)}
                placeholder="0.00"
                className="w-full bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Recovery Type</label>
              <select
                value={formType}
                onChange={e => setFormType(e.target.value)}
                className="w-full bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:border-blue-500 focus:outline-none"
              >
                {RECOVERY_TYPES.map(t => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Notes (optional)</label>
              <textarea
                value={formNotes}
                onChange={e => setFormNotes(e.target.value)}
                rows={2}
                placeholder="Additional context..."
                className="w-full bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:border-blue-500 focus:outline-none resize-none"
              />
            </div>

            {formError && (
              <p className="text-red-400 text-xs">{formError}</p>
            )}

            <button
              type="submit"
              disabled={logMutation.isPending}
              className="w-full px-4 py-2 bg-green-700 hover:bg-green-600 disabled:bg-green-900 disabled:opacity-50 text-white text-sm font-medium rounded transition-colors"
            >
              {logMutation.isPending ? 'Logging...' : 'Log Recovery'}
            </button>
          </form>
        </div>
      </div>

      {/* Recent Recoveries Table */}
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Recent Recoveries</h2>
        {(recoveriesData?.items ?? []).length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
                  <th className="text-left py-2 px-3">NPI</th>
                  <th className="text-right py-2 px-3">Amount</th>
                  <th className="text-left py-2 px-3">Type</th>
                  <th className="text-left py-2 px-3">Date</th>
                  <th className="text-left py-2 px-3">Notes</th>
                  <th className="text-center py-2 px-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {recoveriesData!.items.map(r => (
                  <tr key={r.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 px-3">
                      <Link
                        to={`/providers/${r.npi}`}
                        className="text-blue-400 hover:text-blue-300 font-mono"
                      >
                        {r.npi}
                      </Link>
                    </td>
                    <td className="py-2 px-3 text-right text-green-400 font-mono font-semibold">
                      {fmt(r.amount_recovered)}
                    </td>
                    <td className="py-2 px-3 text-gray-400">
                      {RECOVERY_TYPES.find(t => t.value === r.recovery_type)?.label ?? r.recovery_type}
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs">
                      {new Date(r.recovery_date).toLocaleDateString()}
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs max-w-xs truncate">
                      {r.notes || '--'}
                    </td>
                    <td className="py-2 px-3 text-center">
                      <button
                        onClick={() => {
                          if (confirm('Delete this recovery entry?')) {
                            deleteMutation.mutate(r.id)
                          }
                        }}
                        className="text-gray-600 hover:text-red-400 transition-colors"
                        title="Delete recovery"
                      >
                        <svg className="w-4 h-4 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 text-center text-gray-600 text-sm">
            No recoveries logged yet. Use the form above to log your first recovery.
          </div>
        )}
      </div>

      {/* Top Recoveries */}
      {(summary?.top_recoveries ?? []).length > 0 && (
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Top 10 Recoveries by Amount</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
                  <th className="text-left py-2 px-3">#</th>
                  <th className="text-left py-2 px-3">NPI</th>
                  <th className="text-right py-2 px-3">Amount</th>
                  <th className="text-left py-2 px-3">Type</th>
                  <th className="text-left py-2 px-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {summary!.top_recoveries.map((r, i) => (
                  <tr key={r.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 px-3 text-gray-600">{i + 1}</td>
                    <td className="py-2 px-3">
                      <Link
                        to={`/providers/${r.npi}`}
                        className="text-blue-400 hover:text-blue-300 font-mono"
                      >
                        {r.npi}
                      </Link>
                    </td>
                    <td className="py-2 px-3 text-right text-green-400 font-mono font-semibold">
                      {fmt(r.amount_recovered)}
                    </td>
                    <td className="py-2 px-3 text-gray-400">
                      {RECOVERY_TYPES.find(t => t.value === r.recovery_type)?.label ?? r.recovery_type}
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs">
                      {new Date(r.recovery_date).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
