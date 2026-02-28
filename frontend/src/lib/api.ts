import type {
  Summary,
  ScoredProvider,
  ProviderDetail,
  TimelineRow,
  HcpcsRow,
  NetworkGraph,
  SignalSummary,
  PrescanStatus,
  ReviewItem,
  ReviewCounts,
  OigStatus,
  AddressCluster,
  ProviderPeers,
} from './types'

const BASE = '/api'

async function get<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export const api = {
  summary: () => get<Summary>('/summary'),

  providers: (params: {
    search?: string
    states?: string
    cities?: string
    flag_counts?: string
    min_risk?: number
    max_risk?: number
    min_paid?: number
    max_paid?: number
    min_claims?: number
    max_claims?: number
    min_months?: number
    max_months?: number
    sort_by?: string
    sort_dir?: string
    page?: number
    limit?: number
  }) => get<{ providers: ScoredProvider[]; page: number; limit: number; total: number }>('/providers', params as Record<string, string | number>),

  providerFacets: () => get<{
    states: string[]
    cities: string[]
    flag_counts: number[]
    active_months: number[]
  }>('/providers/facets'),

  providerDetail: (npi: string) => get<ProviderDetail>(`/providers/${npi}`),

  providerTimeline: (npi: string) =>
    get<{ npi: string; timeline: TimelineRow[] }>(`/providers/${npi}/timeline`),

  providerHcpcs: (npi: string) =>
    get<{ npi: string; hcpcs: HcpcsRow[] }>(`/providers/${npi}/hcpcs`),

  anomalies: (params: { signal?: string; state?: string; page?: number; limit?: number }) =>
    get<{ total: number; page: number; limit: number; anomalies: ScoredProvider[] }>(
      '/anomalies',
      params as Record<string, string | number>,
    ),

  signalSummary: () => get<SignalSummary[]>('/anomalies/signals/summary'),

  stateHeatmap: () =>
    get<{
      summary: Record<string, number>
      by_state: { state: string; provider_count: number; total_paid: number; flagged_count: number }[]
    }>('/states/heatmap'),

  network: (npi: string) => get<NetworkGraph>(`/network/${npi}`),

  searchProviders: (q: string) =>
    get<{ npi: string; name: string; state: string; city: string }[]>('/providers/search', { q }),

  prescanStatus: () => get<PrescanStatus>('/prescan/status'),

  scanBatch: (batchSize = 100, stateFilter?: string) =>
    fetch('/api/prescan/scan-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_size: batchSize, state_filter: stateFilter ?? null }),
    }).then(r => r.json()),

  resetScan: () =>
    fetch('/api/prescan/reset', { method: 'POST' }).then(r => r.json()),

  dataStatus: () => get<{
    is_local: boolean
    local_path: string | null
    expected_path: string
    remote_url: string
    file_size_gb: number
    download: { active: boolean; bytes_done: number; bytes_total: number; pct: number; done: boolean; error: string | null }
  }>('/data/status'),

  startDownload: () =>
    fetch('/api/data/download', { method: 'POST' }).then(r => r.json()),

  smartScan: (stateFilter?: string) =>
    fetch('/api/prescan/smart-scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state_filter: stateFilter ?? null }),
    }).then(r => r.json()),

  autoStart: (stateFilter?: string) =>
    fetch('/api/prescan/auto-start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state_filter: stateFilter ?? null }),
    }).then(r => r.json()),

  autoStop: () =>
    fetch('/api/prescan/auto-stop', { method: 'POST' }).then(r => r.json()),

  rescoreAll: () =>
    fetch('/api/prescan/rescore', { method: 'POST' }).then(r => r.json()),

  reviewQueue: (params: { status?: string; page?: number; limit?: number }) =>
    get<{ items: ReviewItem[]; total: number; page: number }>('/review', params as Record<string, string | number>),

  reviewCounts: () => get<ReviewCounts>('/review/counts'),

  exportProvider: (npi: string) => {
    const a = document.createElement('a')
    a.href = `/api/providers/${npi}/export`
    a.download = `provider_${npi}_fraud_package.tar.gz`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  },

  reviewBackfill: () =>
    fetch('/api/review/backfill', { method: 'POST' }).then(r => r.json()),

  updateReview: (npi: string, data: { status?: string; notes?: string }) =>
    fetch(`/api/review/${npi}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  bulkUpdateReview: (data: { npis: string[]; status: string }) =>
    fetch('/api/review/bulk-update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  oigStatus: (npi: string) => get<OigStatus>(`/providers/${npi}/oig`),

  addressCluster: (npi: string) => get<AddressCluster>(`/providers/${npi}/cluster`),

  providerPeers: (npi: string) => get<ProviderPeers>(`/providers/${npi}/peers`),
}
