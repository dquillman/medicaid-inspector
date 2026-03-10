import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { api } from '../lib/api'

// ── Types ────────────────────────────────────────────────────────────────────

interface SupervisedStatus {
  trained: boolean
  trained_at?: number
  total_labeled?: number
  positive_count?: number
  negative_count?: number
  accuracy?: number | null
  precision?: number | null
  recall?: number | null
  f1?: number | null
  auc?: number | null
  confusion_matrix?: number[][] | null
  feature_importance?: Record<string, number>
  cv_folds?: number
  providers_scored?: number
  message?: string
  error?: string
}

interface FeatureImportance {
  features: { feature: string; importance: number }[]
  error?: string
}

interface Prediction {
  npi: string
  fraud_probability: number
  label: number | null
  provider_name?: string
  state?: string
  total_paid?: number
  risk_score?: number
}

interface PredictionsResponse {
  predictions: Prediction[]
  total: number
  limit: number
  offset: number
  error?: string
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number): string {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(2)}`
}

function pct(v: number | null | undefined): string {
  if (v == null) return 'N/A'
  return `${(v * 100).toFixed(1)}%`
}

function probColor(p: number): string {
  if (p >= 0.8) return 'text-red-400'
  if (p >= 0.5) return 'text-orange-400'
  if (p >= 0.3) return 'text-yellow-400'
  return 'text-green-400'
}

function probBg(p: number): string {
  if (p >= 0.8) return 'bg-red-500'
  if (p >= 0.5) return 'bg-orange-500'
  if (p >= 0.3) return 'bg-yellow-500'
  return 'bg-green-500'
}

function metricColor(v: number | null | undefined): string {
  if (v == null) return 'text-gray-500'
  if (v >= 0.8) return 'text-green-400'
  if (v >= 0.6) return 'text-yellow-400'
  return 'text-red-400'
}

const FEATURE_LABELS: Record<string, string> = {
  total_paid: 'Total Paid',
  total_claims: 'Total Claims',
  total_beneficiaries: 'Beneficiaries',
  revenue_per_beneficiary: 'Rev / Bene',
  claims_per_beneficiary: 'Claims / Bene',
  active_months: 'Active Months',
  distinct_hcpcs: 'Distinct HCPCS',
  avg_per_claim: 'Avg / Claim',
  flag_count: 'Flag Count',
  risk_score: 'Risk Score',
  sig_billing_concentration: 'Billing Concentration',
  sig_revenue_per_bene_outlier: 'Rev/Bene Outlier',
  sig_claims_per_bene_anomaly: 'Claims/Bene Anomaly',
  sig_billing_ramp_rate: 'Billing Ramp',
  sig_bust_out_pattern: 'Bust-Out Pattern',
  sig_ghost_billing: 'Ghost Billing',
  sig_total_spend_outlier: 'Total Spend Outlier',
  sig_billing_consistency: 'Billing Consistency',
  sig_bene_concentration: 'Bene Concentration',
  sig_upcoding_pattern: 'Upcoding',
  sig_address_cluster_risk: 'Address Cluster',
  sig_oig_excluded: 'OIG Excluded',
  sig_specialty_mismatch: 'Specialty Mismatch',
  sig_corporate_shell_risk: 'Corporate Shell',
  sig_geographic_impossibility: 'Geo Impossibility',
  sig_dead_npi_billing: 'Dead NPI Billing',
  sig_new_provider_explosion: 'New Provider Explosion',
}

// ── API extensions ───────────────────────────────────────────────────────────

const supervisedApi = {
  status: () =>
    fetch('/api/ml/supervised/status').then(r => r.json()) as Promise<SupervisedStatus>,

  train: () =>
    fetch('/api/ml/supervised/train', { method: 'POST' }).then(r => r.json()) as Promise<SupervisedStatus>,

  featureImportance: () =>
    fetch('/api/ml/supervised/feature-importance').then(r => r.json()) as Promise<FeatureImportance>,

  predictions: (limit = 50, offset = 0) =>
    fetch(`/api/ml/supervised/predictions?limit=${limit}&offset=${offset}`).then(r => {
      if (!r.ok) return r.json().then(d => ({ predictions: [], total: 0, limit, offset, error: d.detail }))
      return r.json()
    }) as Promise<PredictionsResponse>,
}

// ── Component ────────────────────────────────────────────────────────────────

export default function MLModel() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'overview' | 'features' | 'predictions'>('overview')

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['supervised-status'],
    queryFn: supervisedApi.status,
    refetchInterval: 5000,
  })

  const { data: features } = useQuery({
    queryKey: ['supervised-features'],
    queryFn: supervisedApi.featureImportance,
    enabled: !!status?.trained,
  })

  const { data: predictions } = useQuery({
    queryKey: ['supervised-predictions'],
    queryFn: () => supervisedApi.predictions(50, 0),
    enabled: !!status?.trained,
  })

  const trainMutation = useMutation({
    mutationFn: supervisedApi.train,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supervised-status'] })
      queryClient.invalidateQueries({ queryKey: ['supervised-features'] })
      queryClient.invalidateQueries({ queryKey: ['supervised-predictions'] })
    },
  })

  const trained = status?.trained ?? false
  const chartData = (features?.features || [])
    .filter(f => f.importance > 0.001)
    .slice(0, 15)
    .map(f => ({
      name: FEATURE_LABELS[f.feature] || f.feature,
      importance: f.importance,
    }))

  const tabs = [
    { key: 'overview' as const, label: 'Overview' },
    { key: 'features' as const, label: 'Feature Importance' },
    { key: 'predictions' as const, label: 'Top Predictions' },
  ]

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Supervised ML Model</h1>
          <p className="text-sm text-gray-400 mt-1">
            Gradient Boosting classifier trained on confirmed fraud labels from the Review Queue
          </p>
        </div>
        <button
          onClick={() => trainMutation.mutate()}
          disabled={trainMutation.isPending}
          className="btn-primary px-5 py-2.5 flex items-center gap-2"
        >
          {trainMutation.isPending ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Training...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              Train Model
            </>
          )}
        </button>
      </div>

      {/* Training result message */}
      {trainMutation.data && !trainMutation.data.trained && trainMutation.data.error && (
        <div className="border border-yellow-800 bg-yellow-950/30 rounded-lg p-4 text-yellow-300 text-sm">
          <strong>Cannot train:</strong> {trainMutation.data.error}
        </div>
      )}
      {trainMutation.data && trainMutation.data.trained && (
        <div className="border border-green-800 bg-green-950/30 rounded-lg p-4 text-green-300 text-sm">
          Model trained successfully on {trainMutation.data.total_labeled} labeled samples.
          Scored {trainMutation.data.providers_scored} providers.
        </div>
      )}

      {/* Status Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card p-4 text-center">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Status</div>
          <div className={`text-lg font-bold ${trained ? 'text-green-400' : 'text-gray-500'}`}>
            {statusLoading ? '...' : trained ? 'Trained' : 'Untrained'}
          </div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Training Samples</div>
          <div className="text-lg font-bold text-white">
            {status?.total_labeled ?? 0}
            <span className="text-xs text-gray-500 ml-1">
              ({status?.positive_count ?? 0}F / {status?.negative_count ?? 0}C)
            </span>
          </div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Providers Scored</div>
          <div className="text-lg font-bold text-blue-400">
            {status?.providers_scored?.toLocaleString() ?? 0}
          </div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">CV Folds</div>
          <div className="text-lg font-bold text-white">
            {status?.cv_folds ?? 0}
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      {trained && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: 'Accuracy', value: status?.accuracy },
            { label: 'Precision', value: status?.precision },
            { label: 'Recall', value: status?.recall },
            { label: 'F1 Score', value: status?.f1 },
            { label: 'AUC', value: status?.auc },
          ].map(m => (
            <div key={m.label} className="card p-4 text-center">
              <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{m.label}</div>
              <div className={`text-xl font-bold ${metricColor(m.value)}`}>
                {pct(m.value)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confusion Matrix */}
      {trained && status?.confusion_matrix && (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Confusion Matrix (Cross-Validated)</h3>
          <div className="inline-grid grid-cols-3 gap-1 text-sm">
            <div />
            <div className="text-center text-gray-500 text-xs px-4 pb-1">Pred: Clear</div>
            <div className="text-center text-gray-500 text-xs px-4 pb-1">Pred: Fraud</div>
            <div className="text-right text-gray-500 text-xs pr-2">Actual: Clear</div>
            <div className="bg-green-900/40 border border-green-800 rounded px-4 py-2 text-center text-green-300 font-mono">
              {status.confusion_matrix[0]?.[0] ?? 0}
            </div>
            <div className="bg-red-900/20 border border-red-900/50 rounded px-4 py-2 text-center text-red-300 font-mono">
              {status.confusion_matrix[0]?.[1] ?? 0}
            </div>
            <div className="text-right text-gray-500 text-xs pr-2">Actual: Fraud</div>
            <div className="bg-red-900/20 border border-red-900/50 rounded px-4 py-2 text-center text-red-300 font-mono">
              {status.confusion_matrix[1]?.[0] ?? 0}
            </div>
            <div className="bg-green-900/40 border border-green-800 rounded px-4 py-2 text-center text-green-300 font-mono">
              {status.confusion_matrix[1]?.[1] ?? 0}
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      {trained && (
        <>
          <div className="flex gap-1 border-b border-gray-800">
            {tabs.map(t => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                  activeTab === t.key
                    ? 'text-blue-400 border-blue-400'
                    : 'text-gray-500 border-transparent hover:text-gray-300'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="card p-5 space-y-4">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Model Details</h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Algorithm:</span>{' '}
                  <span className="text-white">Gradient Boosting Classifier</span>
                </div>
                <div>
                  <span className="text-gray-500">Trained at:</span>{' '}
                  <span className="text-white">
                    {status?.trained_at ? new Date(status.trained_at * 1000).toLocaleString() : 'N/A'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Feature count:</span>{' '}
                  <span className="text-white">{features?.features?.length ?? 0}</span>
                </div>
                <div>
                  <span className="text-gray-500">Fraud samples:</span>{' '}
                  <span className="text-red-400">{status?.positive_count ?? 0}</span>
                  <span className="text-gray-600 mx-1">|</span>
                  <span className="text-gray-500">Clear samples:</span>{' '}
                  <span className="text-green-400">{status?.negative_count ?? 0}</span>
                </div>
              </div>
              <p className="text-xs text-gray-600 mt-2">
                The model learns from providers marked as "confirmed fraud" / "referred" (positive class)
                and "dismissed" (negative class) in the Review Queue. Re-train as new labels are added.
              </p>
            </div>
          )}

          {/* Feature Importance Tab */}
          {activeTab === 'features' && chartData.length > 0 && (
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
                Top Feature Importances
              </h3>
              <div style={{ width: '100%', height: Math.max(300, chartData.length * 28) }}>
                <ResponsiveContainer>
                  <BarChart data={chartData} layout="vertical" margin={{ left: 140, right: 20, top: 5, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                    <YAxis
                      dataKey="name"
                      type="category"
                      tick={{ fill: '#d1d5db', fontSize: 11 }}
                      width={130}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
                      labelStyle={{ color: '#f3f4f6' }}
                      formatter={(v: number) => [v.toFixed(4), 'Importance']}
                    />
                    <Bar dataKey="importance" radius={[0, 4, 4, 0]}>
                      {chartData.map((_, i) => (
                        <Cell key={i} fill={i < 3 ? '#ef4444' : i < 7 ? '#f59e0b' : '#3b82f6'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Predictions Tab */}
          {activeTab === 'predictions' && (
            <div className="card overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                  Top Fraud Predictions
                </h3>
                <span className="text-xs text-gray-600">
                  {predictions?.total ?? 0} providers scored
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
                      <th className="px-4 py-2">#</th>
                      <th className="px-4 py-2">NPI</th>
                      <th className="px-4 py-2">Provider</th>
                      <th className="px-4 py-2">State</th>
                      <th className="px-4 py-2 text-right">Total Paid</th>
                      <th className="px-4 py-2 text-right">Risk Score</th>
                      <th className="px-4 py-2 text-right">Fraud Prob.</th>
                      <th className="px-4 py-2">Label</th>
                      <th className="px-4 py-2 text-right">Probability Bar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(predictions?.predictions || []).map((p, i) => (
                      <tr key={p.npi} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                        <td className="px-4 py-2 text-gray-600 font-mono text-xs">{i + 1}</td>
                        <td className="px-4 py-2">
                          <Link
                            to={`/providers/${p.npi}`}
                            className="text-blue-400 hover:text-blue-300 font-mono text-xs"
                          >
                            {p.npi}
                          </Link>
                        </td>
                        <td className="px-4 py-2 text-white text-xs truncate max-w-[200px]">
                          {p.provider_name || '-'}
                        </td>
                        <td className="px-4 py-2 text-gray-400 text-xs">{p.state || '-'}</td>
                        <td className="px-4 py-2 text-right text-gray-300 font-mono text-xs">
                          {fmt(p.total_paid ?? 0)}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-300 font-mono text-xs">
                          {(p.risk_score ?? 0).toFixed(1)}
                        </td>
                        <td className={`px-4 py-2 text-right font-bold font-mono text-xs ${probColor(p.fraud_probability)}`}>
                          {(p.fraud_probability * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2 text-xs">
                          {p.label === 1 ? (
                            <span className="px-1.5 py-0.5 rounded bg-red-900/50 text-red-300 text-[10px] uppercase">Fraud</span>
                          ) : p.label === 0 ? (
                            <span className="px-1.5 py-0.5 rounded bg-green-900/50 text-green-300 text-[10px] uppercase">Clear</span>
                          ) : (
                            <span className="text-gray-600">-</span>
                          )}
                        </td>
                        <td className="px-4 py-2">
                          <div className="w-24 h-2 bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${probBg(p.fraud_probability)}`}
                              style={{ width: `${p.fraud_probability * 100}%` }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                    {(!predictions?.predictions || predictions.predictions.length === 0) && (
                      <tr>
                        <td colSpan={9} className="px-4 py-8 text-center text-gray-600">
                          No predictions available. Train the model first.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Untrained state */}
      {!trained && !statusLoading && (
        <div className="card p-8 text-center">
          <div className="text-gray-600 mb-4">
            <svg className="w-16 h-16 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-gray-400 mb-2">Supervised Model Not Yet Trained</h3>
          <p className="text-sm text-gray-600 max-w-md mx-auto mb-4">
            To train the supervised fraud detection model, you need at least 10 labeled providers
            in the Review Queue: mark providers as <strong className="text-red-400">"confirmed fraud"</strong> or{' '}
            <strong className="text-green-400">"dismissed"</strong> to build the training set.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Link to="/review" className="btn-ghost text-sm">
              Go to Review Queue
            </Link>
            <button
              onClick={() => trainMutation.mutate()}
              disabled={trainMutation.isPending}
              className="btn-primary text-sm"
            >
              {trainMutation.isPending ? 'Training...' : 'Try Training'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
