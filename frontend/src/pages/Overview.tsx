import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../lib/api'
import type { PrescanStatus } from '../lib/types'
import StateHeatmap from '../components/StateHeatmap'

const US_STATES = [
  'AK','AL','AR','AZ','CA','CO','CT','DC','DE','FL','GA','HI','IA','ID','IL','IN',
  'KS','KY','LA','MA','MD','ME','MI','MN','MO','MS','MT','NC','ND','NE','NH','NJ',
  'NM','NV','NY','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VA','VT','WA',
  'WI','WV','WY',
]

function DataSourceCard() {
  const queryClient = useQueryClient()

  const { data: ds, isLoading } = useQuery({
    queryKey: ['data-status'],
    queryFn: api.dataStatus,
    refetchInterval: (q) => q.state.data?.download?.active ? 2000 : 30000,
  })

  const handleDownload = async () => {
    if (!confirm('Download the 2.74 GB dataset to local disk? Queries will be ~100x faster once complete.')) return
    await api.startDownload()
    queryClient.invalidateQueries({ queryKey: ['data-status'] })
  }

  if (isLoading || !ds) return null

  const dl = ds.download

  if (ds.is_local) {
    return (
      <div className="card border-green-800 bg-green-950/20 flex items-center justify-between py-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-green-400 font-bold">●</span>
          <span className="text-green-300 font-semibold">Local dataset active</span>
          <span className="text-gray-500">— {ds.file_size_gb} GB on disk · queries run in milliseconds</span>
        </div>
        <span className="text-xs text-gray-600 font-mono truncate max-w-xs">{ds.local_path}</span>
      </div>
    )
  }

  if (dl.active) {
    const gb_done = (dl.bytes_done / 1_073_741_824).toFixed(2)
    const gb_total = (dl.bytes_total / 1_073_741_824).toFixed(2)
    return (
      <div className="card border-blue-800 bg-blue-950/20 space-y-2 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span className="text-blue-300 font-semibold">Downloading dataset…</span>
            <span className="text-gray-400 font-mono text-xs">{gb_done} / {gb_total} GB</span>
          </div>
          <span className="text-blue-400 font-mono text-sm">{dl.pct}%</span>
        </div>
        <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${dl.pct}%` }} />
        </div>
        <p className="text-xs text-gray-500">Scans will be ~100× faster once complete. You can still scan while downloading.</p>
      </div>
    )
  }

  if (dl.error) {
    return (
      <div className="card border-red-800 bg-red-950/20 flex items-center justify-between py-3">
        <span className="text-red-400 text-sm">Download failed: {dl.error}</span>
        <button onClick={handleDownload} className="text-xs text-blue-400 hover:text-blue-300">Retry</button>
      </div>
    )
  }

  // Remote mode — prompt to download or point to existing file
  return (
    <div className="card border-yellow-800 bg-yellow-950/20 space-y-2 py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-yellow-400 font-bold">⚠</span>
            <span className="text-yellow-300 font-semibold">Using remote dataset</span>
            <span className="text-gray-500">— each scan batch takes 10–30s over the network</span>
          </div>
          <p className="text-xs text-gray-500 ml-5">Download once (2.74 GB) to make scans ~100× faster</p>
        </div>
        <button
          onClick={handleDownload}
          className="px-4 py-2 bg-yellow-700 hover:bg-yellow-600 text-white text-sm font-medium rounded transition-colors shrink-0"
        >
          Download Locally
        </button>
      </div>
      {ds.expected_path && (
        <div className="ml-5 space-y-1">
          <p className="text-xs text-gray-500">
            App is looking for the file at:
          </p>
          <p className="text-xs font-mono bg-gray-800 text-gray-300 px-2 py-1 rounded break-all">
            {ds.expected_path}
          </p>
          <p className="text-xs text-gray-600">
            Already have the file elsewhere? Add this line to{' '}
            <span className="font-mono text-gray-400">backend/.env</span>
            {' '}and restart the backend:
          </p>
          <p className="text-xs font-mono bg-gray-800 text-blue-300 px-2 py-1 rounded">
            LOCAL_PARQUET_PATH=C:/path/to/medicaid-provider-spending.parquet
          </p>
        </div>
      )}
    </div>
  )
}


function ScanControl({
  status,
  cachedCount,
  isLocal,
  onScanBatch,
  onReset,
  onAutoStart,
  onAutoStop,
  onRescore,
  onSmartScan,
}: {
  status: PrescanStatus | undefined
  cachedCount: number
  isLocal: boolean
  onScanBatch: (stateFilter: string) => void
  onReset: () => void
  onAutoStart: (stateFilter: string) => void
  onAutoStop: () => void
  onRescore: () => void
  onSmartScan: (stateFilter: string) => void
}) {
  const [stateFilter, setStateFilter] = useState('')
  const isScanning = status ? status.phase > 0 : false
  const isAutoMode = status?.auto_mode === true
  const isSmartScan = status?.smart_scan_mode === true
  const progress = status?.scan_progress
  const scanned = progress?.offset ?? 0
  const total = progress?.total_provider_count ?? 0
  const pct = total > 0 ? Math.min(100, Math.round((scanned / total) * 100)) : 0
  const activeFilter = progress?.state_filter

  const mins = Math.floor((status?.elapsed_sec ?? 0) / 60)
  const secs = (status?.elapsed_sec ?? 0) % 60

  return (
    <div className={`card space-y-4 ${isSmartScan ? 'border-purple-700 bg-purple-950/20' : 'border-blue-800 bg-blue-950/30'}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isScanning && (
            <span className={`w-2 h-2 rounded-full animate-pulse ${isSmartScan ? 'bg-purple-400' : 'bg-blue-400'}`} />
          )}
          <span className="text-white text-sm font-semibold">Provider Scan</span>
          {isScanning && (
            <span className="text-gray-500 text-xs font-mono">
              {mins > 0 ? `${mins}m ` : ''}{secs}s
            </span>
          )}
          {isSmartScan && (
            <span className="text-xs bg-purple-900 text-purple-300 px-2 py-0.5 rounded-full font-medium">
              Smart Scan
            </span>
          )}
          {isAutoMode && !isSmartScan && (
            <span className="text-xs bg-blue-900 text-blue-300 px-2 py-0.5 rounded-full font-medium">
              Auto
            </span>
          )}
        </div>
        {progress && progress.batches_completed > 0 && (
          <span className="text-gray-500 text-xs">
            {progress.batches_completed} batch{progress.batches_completed !== 1 ? 'es' : ''} completed
          </span>
        )}
      </div>

      {/* Smart scan Phase-1 banner (loading all providers — no progress bar yet) */}
      {isSmartScan && total === 0 && isScanning && (
        <div className="rounded-lg bg-purple-900/30 border border-purple-800 px-4 py-3 space-y-2">
          <p className="text-sm text-purple-200 font-medium">{status?.message}</p>
          <div className="w-full h-1.5 bg-purple-900 rounded-full overflow-hidden">
            <div className="h-full bg-purple-400 rounded-full animate-pulse" style={{ width: '100%' }} />
          </div>
          <p className="text-xs text-purple-400">
            Phase 1: querying all providers at once — this may take 30–60s with local data.
          </p>
        </div>
      )}

      {/* Smart scan Phase-2 progress */}
      {isSmartScan && total > 0 && (
        <div className="rounded-lg bg-purple-900/30 border border-purple-800 px-4 py-3 space-y-2">
          <p className="text-sm text-purple-200 font-medium">{status?.message}</p>
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-purple-300">
              <span>{scanned.toLocaleString()} of {total.toLocaleString()} candidates scored</span>
              <span className="font-mono">{pct}%</span>
            </div>
            <div className="w-full h-2 bg-purple-900 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 rounded-full transition-all duration-700"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* State filter */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-400 shrink-0">State filter:</label>
        <select
          value={stateFilter}
          onChange={e => setStateFilter(e.target.value)}
          disabled={isScanning}
          className="bg-gray-800 text-white text-xs rounded px-2 py-1 border border-gray-700 disabled:opacity-50"
        >
          <option value="">All States</option>
          {US_STATES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        {activeFilter && (
          <span className="text-xs text-blue-400">
            Currently scanning: <span className="font-mono font-bold">{activeFilter}</span>
          </span>
        )}
      </div>

      {/* Progress bar — regular scan only */}
      {!isSmartScan && total > 0 && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span>{scanned.toLocaleString()} of {total.toLocaleString()} providers scanned</span>
            <span className="font-mono">{pct}%</span>
          </div>
          <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-700"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {/* Status message — regular scan only (smart scan shows its own banner above) */}
      {!isSmartScan && status?.message && (
        <p className="text-xs text-gray-400">{status.message}</p>
      )}

      {/* Action buttons */}
      <div className="flex gap-3 items-center flex-wrap">
        {isLocal && !isScanning && !isAutoMode && (
          <button
            onClick={() => onSmartScan(stateFilter)}
            className="px-4 py-2 bg-purple-700 hover:bg-purple-600 text-white text-sm font-medium rounded transition-colors flex items-center gap-1.5"
            title="Scans ALL providers at once, surfaces only the highest-risk candidates — requires local data"
          >
            <span>&#9678;</span> Find High-Risk Providers
          </button>
        )}
        {isAutoMode ? (
          <button
            onClick={onAutoStop}
            className="px-4 py-2 bg-orange-700 hover:bg-orange-600 text-white text-sm font-medium rounded transition-colors flex items-center gap-1.5"
          >
            <span>&#9632;</span> Stop Auto Scan
          </button>
        ) : (
          <button
            onClick={() => onAutoStart(stateFilter)}
            disabled={isScanning}
            className="px-4 py-2 bg-green-700 hover:bg-green-600 disabled:bg-green-900 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded transition-colors flex items-center gap-1.5"
          >
            <span>&#9654;</span> Start Auto Scan
          </button>
        )}
        <button
          onClick={() => onScanBatch(stateFilter)}
          disabled={isScanning || isAutoMode}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded transition-colors"
        >
          {isScanning && !isAutoMode ? 'Scanning…' : 'Scan Next 100'}
        </button>
        {cachedCount > 0 && !isScanning && !isAutoMode && (
          <button
            onClick={onRescore}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-yellow-400 hover:text-yellow-300 text-sm rounded transition-colors border border-gray-700"
            title="Re-run fraud signals on all cached providers using updated logic — no re-scanning needed"
          >
            Re-score All ({cachedCount.toLocaleString()})
          </button>
        )}
        {cachedCount > 0 && !isScanning && !isAutoMode && (
          <button
            onClick={onReset}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-red-400 hover:text-red-300 text-sm rounded transition-colors border border-gray-700"
          >
            Reset Scan
          </button>
        )}
        {total === 0 && !isScanning && scanned === 0 && (
          <span className="text-xs text-gray-500">
            First scan will count all providers in the dataset.
          </span>
        )}
      </div>
    </div>
  )
}

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v}`
}

const SIGNAL_LABELS: Record<string, string> = {
  billing_concentration:    'Billing Concentration',
  revenue_per_bene_outlier: 'Revenue Outlier',
  claims_per_bene_anomaly:  'Claims Anomaly',
  billing_ramp_rate:        'Billing Ramp',
  bust_out_pattern:         'Bust-Out',
  ghost_billing:            'Ghost Billing',
  total_spend_outlier:      'Total Spend Outlier',
  billing_consistency:      'Billing Consistency',
}

export default function Overview() {
  const queryClient = useQueryClient()

  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ['summary'],
    queryFn: api.summary,
    refetchInterval: 5000,
  })

  const { data: prescanStatus } = useQuery({
    queryKey: ['prescan-status'],
    queryFn: api.prescanStatus,
    refetchInterval: (query) => {
      const phase = query.state.data?.phase ?? 0
      return phase > 0 ? 2000 : 5000
    },
  })

  const { data: signals } = useQuery({
    queryKey: ['signal-summary'],
    queryFn: api.signalSummary,
    refetchInterval: 10000,
  })

  const { data: heatmap } = useQuery({
    queryKey: ['state-heatmap'],
    queryFn: api.stateHeatmap,
    refetchInterval: 15000,
  })

  const { data: ds } = useQuery({
    queryKey: ['data-status'],
    queryFn: api.dataStatus,
    refetchInterval: 30000,
  })

  const handleScanBatch = useCallback(async (stateFilter: string) => {
    await api.scanBatch(100, stateFilter || undefined)
    // Summary and signals will refresh via their own polling intervals
    queryClient.invalidateQueries({ queryKey: ['prescan-status'] })
  }, [queryClient])

  const handleReset = useCallback(async () => {
    if (!confirm('Reset all scan results and start over?')) return
    await api.resetScan()
    queryClient.invalidateQueries({ queryKey: ['summary'] })
    queryClient.invalidateQueries({ queryKey: ['prescan-status'] })
    queryClient.invalidateQueries({ queryKey: ['signal-summary'] })
    queryClient.invalidateQueries({ queryKey: ['state-heatmap'] })
  }, [queryClient])

  const handleAutoStart = useCallback(async (stateFilter: string) => {
    await api.autoStart(stateFilter || undefined)
    queryClient.invalidateQueries({ queryKey: ['prescan-status'] })
  }, [queryClient])

  const handleAutoStop = useCallback(async () => {
    await api.autoStop()
    queryClient.invalidateQueries({ queryKey: ['prescan-status'] })
  }, [queryClient])

  const handleRescore = useCallback(async () => {
    await api.rescoreAll()
    queryClient.invalidateQueries({ queryKey: ['summary'] })
    queryClient.invalidateQueries({ queryKey: ['signal-summary'] })
    queryClient.invalidateQueries({ queryKey: ['review-counts'] })
    queryClient.invalidateQueries({ queryKey: ['review-queue'] })
  }, [queryClient])

  const handleSmartScan = useCallback(async (stateFilter: string) => {
    if (!confirm(
      'Find High-Risk Providers will load ALL providers from the local dataset at once, ' +
      'pre-screen them with statistical thresholds, then fully score only the candidates.\n\n' +
      'This replaces your current scan cache. Continue?'
    )) return
    await api.smartScan(stateFilter || undefined)
    queryClient.invalidateQueries({ queryKey: ['prescan-status'] })
    queryClient.invalidateQueries({ queryKey: ['summary'] })
  }, [queryClient])

  const kpis = [
    { label: 'Total Spend', value: summary ? fmt(summary.total_paid) : '—', color: 'text-blue-400', sub: null },
    { label: 'Providers Scanned', value: summary ? summary.total_providers.toLocaleString() : '—', color: 'text-purple-400', sub: null },
    { label: 'Flagged for Review', value: summary ? summary.flagged_providers.toLocaleString() : '—', color: 'text-yellow-400', sub: 'score ≥ 10' },
    { label: 'High Risk', value: summary ? (summary.high_risk_providers ?? 0).toLocaleString() : '—', color: 'text-red-400', sub: 'score ≥ 50' },
  ]

  const barData = (signals ?? []).map(s => ({
    name: SIGNAL_LABELS[s.signal] ?? s.signal,
    count: s.count,
  }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard Overview</h1>
        <p className="text-gray-400 text-sm mt-1">
          Medicaid provider-level claims · 2018–2024 · 220M+ rows streamed via DuckDB
        </p>
      </div>

      <DataSourceCard />

      <ScanControl
        status={prescanStatus}
        cachedCount={summary?.total_providers ?? 0}
        isLocal={ds?.is_local ?? false}
        onScanBatch={handleScanBatch}
        onReset={handleReset}
        onAutoStart={handleAutoStart}
        onAutoStop={handleAutoStop}
        onRescore={handleRescore}
        onSmartScan={handleSmartScan}
      />

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4">
        {kpis.map(kpi => (
          <div key={kpi.label} className="card">
            <div className="flex items-center gap-2">
              <p className="text-gray-500 text-xs uppercase tracking-wider">{kpi.label}</p>
              {kpi.sub && (
                <span className="text-gray-600 text-xs">{kpi.sub}</span>
              )}
            </div>
            <p className={`text-3xl font-bold mt-2 ${kpi.color} ${sumLoading ? 'animate-pulse' : ''}`}>
              {sumLoading ? '…' : kpi.value}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* State heatmap */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Flagged Providers by State</h2>
          <div className="h-64">
            {heatmap ? (
              <StateHeatmap data={heatmap.by_state} />
            ) : (
              <div className="h-full flex items-center justify-center text-gray-600 text-sm">
                Loading map…
              </div>
            )}
          </div>
          <p className="text-xs text-gray-600 mt-2">Color intensity = flagged provider count. State data from NPPES.</p>
        </div>

        {/* Fraud signals bar chart */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Top Fraud Signals (provider count)</h2>
          {barData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={barData} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} />
                <YAxis
                  type="category" dataKey="name" width={140}
                  tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} axisLine={false}
                />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                  formatter={(v: number) => [v.toLocaleString(), 'Providers']}
                />
                <Bar dataKey="count" fill="#ef4444" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-600 text-sm">
              Scan some providers to see fraud signals…
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
