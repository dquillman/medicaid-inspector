import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { PrescanStatus } from '../lib/types'

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
        <p className="text-xs text-gray-500">Scans will be ~100× faster once complete.</p>
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
          <p className="text-xs text-gray-500">App is looking for the file at:</p>
          <p className="text-xs font-mono bg-gray-800 text-gray-300 px-2 py-1 rounded break-all">{ds.expected_path}</p>
          <p className="text-xs text-gray-600">
            Already have the file elsewhere? Add this line to{' '}
            <span className="font-mono text-gray-400">backend/.env</span>{' '}and restart the backend:
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

      {isSmartScan && total > 0 && (
        <div className="rounded-lg bg-purple-900/30 border border-purple-800 px-4 py-3 space-y-2">
          <p className="text-sm text-purple-200 font-medium">{status?.message}</p>
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-purple-300">
              <span>{scanned.toLocaleString()} of {total.toLocaleString()} candidates scored</span>
              <span className="font-mono">{pct}%</span>
            </div>
            <div className="w-full h-2 bg-purple-900 rounded-full overflow-hidden">
              <div className="h-full bg-purple-500 rounded-full transition-all duration-700" style={{ width: `${pct}%` }} />
            </div>
          </div>
        </div>
      )}

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

      {!isSmartScan && total > 0 && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span>{scanned.toLocaleString()} of {total.toLocaleString()} providers scanned</span>
            <span className="font-mono">{pct}%</span>
          </div>
          <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full transition-all duration-700" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {!isSmartScan && status?.message && (
        <p className="text-xs text-gray-400">{status.message}</p>
      )}

      <div className="flex gap-3 items-center flex-wrap">
        {isLocal && !isScanning && !isAutoMode && (
          <button
            onClick={() => onSmartScan(stateFilter)}
            className="px-4 py-2 bg-purple-700 hover:bg-purple-600 text-white text-sm font-medium rounded transition-colors flex items-center gap-1.5"
            title="Scans ALL providers at once, surfaces only the highest-risk candidates"
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
            title="Re-run fraud signals on all cached providers using updated logic"
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

export default function AdminScan() {
  const queryClient = useQueryClient()

  const { data: summary } = useQuery({
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

  const { data: ds } = useQuery({
    queryKey: ['data-status'],
    queryFn: api.dataStatus,
    refetchInterval: 30000,
  })

  const handleScanBatch = useCallback(async (stateFilter: string) => {
    await api.scanBatch(100, stateFilter || undefined)
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white uppercase tracking-wide">
          Scan Administration
        </h1>
        <p className="text-gray-500 text-xs mt-1 uppercase tracking-wider">
          Manage data sources, provider scanning, and rescoring
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

      {/* ML Model Training */}
      <div className="card space-y-3">
        <h2 className="text-sm font-semibold text-gray-300">ML Anomaly Detection (Isolation Forest)</h2>
        <p className="text-xs text-gray-500">
          Train an unsupervised ML model on all cached providers to detect statistical outliers
          beyond rule-based signals.
        </p>
        <button
          onClick={async () => {
            const result = await api.trainMl()
            alert(`ML model trained: ${result.provider_count} providers, ${result.anomaly_count} anomalies detected`)
            queryClient.invalidateQueries({ queryKey: ['ml-status'] })
          }}
          disabled={!summary?.total_providers}
          className="px-4 py-2 bg-indigo-700 hover:bg-indigo-600 disabled:bg-indigo-900 disabled:opacity-50 text-white text-sm font-medium rounded transition-colors"
        >
          Train ML Model
        </button>
      </div>

      {/* Dataset Discovery & Refresh */}
      <DatasetInfoCard />

      {/* Data Quality Validation */}
      <DataQualityCard />

      {/* Data Lineage */}
      <DataLineageCard />
    </div>
  )
}


/* ────────────────────────────────────────────────────────────────────────────
   Dataset Info & Auto-Refresh Card (#8)
   ──────────────────────────────────────────────────────────────────────────── */
function DatasetInfoCard() {
  const queryClient = useQueryClient()
  const [checking, setChecking] = useState(false)
  const [refreshResult, setRefreshResult] = useState<{
    update_available: boolean; message: string; new_url?: string | null; new_date?: string | null
  } | null>(null)

  const { data: info } = useQuery({
    queryKey: ['dataset-info'],
    queryFn: api.datasetInfo,
    refetchInterval: 60000,
  })

  const handleCheck = async () => {
    setChecking(true)
    try {
      const result = await api.datasetRefresh()
      setRefreshResult(result)
      queryClient.invalidateQueries({ queryKey: ['dataset-info'] })
    } finally {
      setChecking(false)
    }
  }

  const handleSwitch = async (url: string) => {
    if (!confirm(`Switch to the newer dataset?\n\nURL: ${url}\n\nYou will need to re-scan providers after switching.`)) return
    await api.datasetSwitch(url)
    setRefreshResult(null)
    queryClient.invalidateQueries({ queryKey: ['dataset-info'] })
    queryClient.invalidateQueries({ queryKey: ['data-status'] })
  }

  return (
    <div className="card space-y-3">
      <h2 className="text-sm font-semibold text-gray-300">Dataset Information</h2>

      {info ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
          <div>
            <span className="text-gray-500">Dataset Date:</span>{' '}
            <span className="text-white font-mono">{info.detected_date || 'Unknown'}</span>
          </div>
          <div>
            <span className="text-gray-500">Row Count:</span>{' '}
            <span className="text-white font-mono">{info.row_count?.toLocaleString() ?? 'Not yet counted'}</span>
          </div>
          <div className="col-span-2">
            <span className="text-gray-500">Active Path:</span>{' '}
            <span className="text-gray-300 font-mono text-[11px] break-all">{info.active_path}</span>
          </div>
          <div className="col-span-2">
            <span className="text-gray-500">Source:</span>{' '}
            <span className={`font-medium ${info.is_local ? 'text-green-400' : 'text-yellow-400'}`}>
              {info.is_local ? 'Local file' : 'Remote URL'}
            </span>
          </div>
          {info.last_checked && (
            <div className="col-span-2">
              <span className="text-gray-500">Last checked for updates:</span>{' '}
              <span className="text-gray-400">{new Date(info.last_checked * 1000).toLocaleString()}</span>
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-gray-500">Loading dataset info...</p>
      )}

      <div className="flex gap-3 items-center">
        <button
          onClick={handleCheck}
          disabled={checking}
          className="px-4 py-2 bg-cyan-700 hover:bg-cyan-600 disabled:bg-cyan-900 disabled:opacity-50 text-white text-sm font-medium rounded transition-colors"
        >
          {checking ? 'Checking...' : 'Check for Updates'}
        </button>
      </div>

      {refreshResult && (
        <div className={`rounded-lg px-4 py-3 text-xs ${
          refreshResult.update_available
            ? 'bg-green-950/30 border border-green-800 text-green-300'
            : 'bg-gray-800/50 border border-gray-700 text-gray-400'
        }`}>
          <p>{refreshResult.message}</p>
          {refreshResult.update_available && refreshResult.new_url && (
            <div className="mt-2 space-y-1">
              <p className="text-gray-400">New version: <span className="font-mono text-green-300">{refreshResult.new_date}</span></p>
              <button
                onClick={() => handleSwitch(refreshResult.new_url!)}
                className="px-3 py-1 bg-green-700 hover:bg-green-600 text-white text-xs font-medium rounded transition-colors"
              >
                Switch to New Dataset
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


/* ────────────────────────────────────────────────────────────────────────────
   Data Quality Validation Card (#9)
   ──────────────────────────────────────────────────────────────────────────── */
function DataQualityCard() {
  const queryClient = useQueryClient()
  const [running, setRunning] = useState(false)

  const { data: quality } = useQuery({
    queryKey: ['data-quality'],
    queryFn: api.dataQuality,
    refetchInterval: 30000,
  })

  const handleRun = async () => {
    setRunning(true)
    try {
      await api.runDataQuality(5000)
      queryClient.invalidateQueries({ queryKey: ['data-quality'] })
    } finally {
      setRunning(false)
    }
  }

  const q = quality
  const hasResults = q && q.status !== 'never_run'

  return (
    <div className="card space-y-3">
      <h2 className="text-sm font-semibold text-gray-300">Data Quality Validation</h2>
      <p className="text-xs text-gray-500">
        Validates NPI format (Luhn check), claim amounts, and date ranges against the active dataset.
        Runs automatically on first scan batch.
      </p>

      {hasResults && (
        <div className="space-y-3">
          {/* Quality score bar */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400 w-20 shrink-0">Quality Score</span>
            <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  q.quality_score >= 95 ? 'bg-green-500' :
                  q.quality_score >= 80 ? 'bg-yellow-500' : 'bg-red-500'
                }`}
                style={{ width: `${q.quality_score}%` }}
              />
            </div>
            <span className={`text-sm font-bold font-mono ${
              q.quality_score >= 95 ? 'text-green-400' :
              q.quality_score >= 80 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {q.quality_score}%
            </span>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-4 gap-3">
            <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
              <div className="text-lg font-bold text-white">{q.total_dataset_rows?.toLocaleString()}</div>
              <div className="text-[10px] text-gray-500 uppercase">Total Rows</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
              <div className="text-lg font-bold text-green-400">{q.valid_records?.toLocaleString()}</div>
              <div className="text-[10px] text-gray-500 uppercase">Valid</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
              <div className="text-lg font-bold text-red-400">{q.invalid_records}</div>
              <div className="text-[10px] text-gray-500 uppercase">Invalid</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
              <div className="text-lg font-bold text-yellow-400">{q.sample_size?.toLocaleString()}</div>
              <div className="text-[10px] text-gray-500 uppercase">Sampled</div>
            </div>
          </div>

          {/* Failure breakdown */}
          {q.failures && Object.keys(q.failures).length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-gray-400 font-medium">Validation Failures</p>
              <div className="grid grid-cols-2 gap-1 text-xs">
                {Object.entries(q.failures).map(([key, count]) => (
                  <div key={key} className="flex justify-between bg-gray-800/30 rounded px-2 py-1">
                    <span className="text-gray-400">{key.replace(/_/g, ' ')}</span>
                    <span className="text-red-400 font-mono">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {q.last_run && (
            <p className="text-[10px] text-gray-600">
              Last run: {new Date(q.last_run * 1000).toLocaleString()}
              {(q as any).elapsed_sec !== undefined && ` (${(q as any).elapsed_sec}s)`}
            </p>
          )}
        </div>
      )}

      <button
        onClick={handleRun}
        disabled={running}
        className="px-4 py-2 bg-amber-700 hover:bg-amber-600 disabled:bg-amber-900 disabled:opacity-50 text-white text-sm font-medium rounded transition-colors"
      >
        {running ? 'Validating...' : hasResults ? 'Re-run Validation' : 'Run Data Validation'}
      </button>
    </div>
  )
}


/* ────────────────────────────────────────────────────────────────────────────
   Data Lineage Card (#11)
   ──────────────────────────────────────────────────────────────────────────── */
function DataLineageCard() {
  const { data: lineage } = useQuery({
    queryKey: ['data-lineage'],
    queryFn: () => api.dataLineage(1, 10),
    refetchInterval: 30000,
  })

  const entries = lineage?.entries ?? []
  const summary = lineage?.summary

  return (
    <div className="card space-y-3">
      <h2 className="text-sm font-semibold text-gray-300">Data Lineage</h2>
      <p className="text-xs text-gray-500">
        Tracks which dataset version was used for each scan, when it ran, and how many providers/claims were processed.
      </p>

      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
            <div className="text-lg font-bold text-white">{summary.total_scans}</div>
            <div className="text-[10px] text-gray-500 uppercase">Total Scans</div>
          </div>
          <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
            <div className="text-lg font-bold text-blue-400">{summary.dataset_versions_seen}</div>
            <div className="text-[10px] text-gray-500 uppercase">Dataset Versions</div>
          </div>
          <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-center">
            <div className="text-lg font-bold text-gray-300">
              {summary.latest_scan ? new Date(summary.latest_scan * 1000).toLocaleDateString() : '--'}
            </div>
            <div className="text-[10px] text-gray-500 uppercase">Latest Scan</div>
          </div>
        </div>
      )}

      {entries.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-1 pr-3">When</th>
                <th className="text-left py-1 pr-3">Type</th>
                <th className="text-left py-1 pr-3">Dataset Date</th>
                <th className="text-right py-1 pr-3">Providers</th>
                <th className="text-right py-1 pr-3">Claims</th>
                <th className="text-right py-1">Duration</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="py-1.5 pr-3 text-gray-400">{new Date(e.timestamp * 1000).toLocaleString()}</td>
                  <td className="py-1.5 pr-3">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      e.scan_type === 'smart' ? 'bg-purple-900 text-purple-300' :
                      e.scan_type === 'rescore' ? 'bg-yellow-900 text-yellow-300' :
                      'bg-blue-900 text-blue-300'
                    }`}>
                      {e.scan_type}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-gray-300 font-mono">{e.dataset_date || '--'}</td>
                  <td className="py-1.5 pr-3 text-right text-white font-mono">{e.provider_count.toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right text-gray-300 font-mono">{e.total_claims.toLocaleString()}</td>
                  <td className="py-1.5 text-right text-gray-400 font-mono">
                    {e.duration_sec != null ? `${e.duration_sec.toFixed(1)}s` : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-gray-600">No scan history yet. Run a scan to start tracking lineage.</p>
      )}
    </div>
  )
}
