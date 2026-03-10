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
  AuditEntry,
  OigStatus,
  AddressCluster,
  ProviderPeers,
  PeerDistribution,
  OpenPaymentsData,
  SamExclusion,
  AlertRule,
  AlertCondition,
  AlertRuleResult,
  CaseStats,
  AuditLogResponse,
  AuditLogEntry,
  AuditStats,
  OwnershipChain,
  OwnershipNetworksResponse,
  ClaimLinesResponse,
  HcpcsDetailResponse,
  ROISummary,
  RecoveryRecord,
  ExclusionSummary,
  BatchExclusionResults,
  BillingNetwork,
  DataSourcesResponse,
  BillingForecast,
  YoyComparison,
  TimelineAnalysis,
  RelatedProvidersResponse,
  WatchlistResponse,
  WatchlistAlertsResponse,
  WatchlistEntry,
  SpecialtyListItem,
  SpecialtyStats,
  SpecialtyOutlier,
  SpecialtyRank,
  MedicareUtilization,
  MedicareComparison,
  FraudRingsResponse,
  FraudRingDetail,
  ScoreTrendResponse,
  ScoreMoversResponse,
  ScoreSummaryResponse,
  NewsAlertsResponse,
  NewsAlert,
  TemporalAnalysis,
  SystemTemporalPatterns,
  LicenseVerification,
  LicenseFlagsResponse,
  PharmacyHighRiskResponse,
  PharmacyProviderDetail,
  DMEHighRiskResponse,
  DMEProviderDetail,
  MMISStatus,
  MMISEligibility,
  MMISEnrollment,
  NPPESBulkStatus,
  DEAStatus,
  SMTPStatus,
  FHIRPractitioner,
  FHIRDocumentReference,
  PHILogResponse,
  PHILogStats,
  RetentionStatus,
  RetentionPolicy,
  EvidenceRecord,
  EvidenceListResponse,
  MFCUReferral,
  ReferralsResponse,
  ReferralStats,
} from './types'

const BASE = '/api'

function authHeaders(): Record<string, string> {
  try {
    const session = JSON.parse(localStorage.getItem('mfi_session') || '{}')
    if (session.token) {
      return { 'Authorization': `Bearer ${session.token}` }
    }
  } catch {
    // ignore parse errors
  }
  return {}
}

async function get<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString(), { headers: { ...authHeaders() } })
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
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ batch_size: batchSize, state_filter: stateFilter ?? null }),
    }).then(r => r.json()),

  resetScan: () =>
    fetch('/api/prescan/reset', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  dataStatus: () => get<{
    is_local: boolean
    local_path: string | null
    expected_path: string
    remote_url: string
    file_size_gb: number
    download: { active: boolean; bytes_done: number; bytes_total: number; pct: number; done: boolean; error: string | null }
  }>('/data/status'),

  startDownload: () =>
    fetch('/api/data/download', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  smartScan: (stateFilter?: string) =>
    fetch('/api/prescan/smart-scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ state_filter: stateFilter ?? null }),
    }).then(r => r.json()),

  autoStart: (stateFilter?: string) =>
    fetch('/api/prescan/auto-start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ state_filter: stateFilter ?? null }),
    }).then(r => r.json()),

  autoStop: () =>
    fetch('/api/prescan/auto-stop', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  rescoreAll: () =>
    fetch('/api/prescan/rescore', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

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
    fetch('/api/review/backfill', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  updateReview: (npi: string, data: { status?: string; notes?: string; assigned_to?: string | null }) =>
    fetch(`/api/review/${npi}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  getReviewHistory: (npi: string) =>
    get<{ npi: string; audit_trail: AuditEntry[] }>(`/review/${npi}/history`),

  bulkUpdateReview: (data: { npis: string[]; status: string }) =>
    fetch('/api/review/bulk-update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  oigStatus: (npi: string) => get<OigStatus>(`/providers/${npi}/oig`),

  addressCluster: (npi: string) => get<AddressCluster>(`/providers/${npi}/cluster`),

  providerPeers: (npi: string) => get<ProviderPeers>(`/providers/${npi}/peers`),

  peerDistribution: (npi: string) => get<PeerDistribution>(`/providers/${npi}/peer-distribution`),

  openPayments: (npi: string) => get<OpenPaymentsData>(`/providers/${npi}/open-payments`),

  samExclusion: (npi: string) => get<SamExclusion>(`/providers/${npi}/sam-exclusion`),

  signalEvidence: (npi: string, signal: string) =>
    get<Record<string, unknown>>(`/providers/${npi}/signal-evidence/${signal}`),

  // ML Anomaly Scoring
  mlScore: (npi: string) => get<{
    npi: string
    ml_anomaly_score: number | null
    ml_percentile: number | null
    feature_importances: Record<string, number> | null
    note?: string
  }>(`/providers/${npi}/ml-score`),

  trainMl: () =>
    fetch('/api/ml/train', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  mlStatus: () => get<{
    trained: boolean
    provider_count?: number
    anomaly_count?: number
    scores_available?: number
    message?: string
  }>('/ml/status'),

  // Alert Rules
  alertRules: () => get<{ rules: AlertRule[] }>('/alerts/rules'),

  createAlertRule: (data: { name: string; conditions: AlertCondition[]; enabled?: boolean }) =>
    fetch('/api/alerts/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  updateAlertRule: (id: string, data: { name?: string; conditions?: AlertCondition[]; enabled?: boolean }) =>
    fetch(`/api/alerts/rules/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  deleteAlertRule: (id: string) =>
    fetch(`/api/alerts/rules/${id}`, { method: 'DELETE', headers: { ...authHeaders() } }).then(r => r.json()),

  evaluateAlerts: () =>
    fetch('/api/alerts/evaluate', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()) as Promise<{ results: AlertRuleResult[]; provider_count: number }>,

  alertResults: () => get<{ results: AlertRuleResult[] }>('/alerts/results'),

  // Case Management
  caseStats: () => get<CaseStats>('/cases/stats'),

  caseOverdue: () => get<{ items: ReviewItem[]; total: number }>('/cases/overdue'),

  addCaseDocument: (npi: string, data: { filename: string; description?: string; data_type?: string }) =>
    fetch(`/api/cases/${npi}/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  logCaseHours: (npi: string, data: { hours: number; description?: string }) =>
    fetch(`/api/cases/${npi}/hours`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()),

  setCasePriority: (npi: string, priority: string) =>
    fetch(`/api/cases/${npi}/priority`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ priority }),
    }).then(r => r.json()),

  setCaseDueDate: (npi: string, due_date: string | null) =>
    fetch(`/api/cases/${npi}/due-date`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ due_date }),
    }).then(r => r.json()),

  // Audit Log
  auditLog: (params: {
    action_type?: string
    entity_type?: string
    entity_id?: string
    date_from?: number
    date_to?: number
    page?: number
    limit?: number
  }) => get<AuditLogResponse>('/audit/log', params as Record<string, string | number>),

  auditEntityHistory: (entityType: string, entityId: string) =>
    get<{ entity_type: string; entity_id: string; entries: AuditLogEntry[] }>(`/audit/log/${entityType}/${entityId}`),

  auditStats: () => get<AuditStats>('/audit/stats'),

  // Ownership Chain
  ownershipChain: (npi: string) => get<OwnershipChain>(`/providers/${npi}/ownership-chain`),

  ownershipNetworks: () => get<OwnershipNetworksResponse>('/ownership/networks'),

  // Claim-Level Drill-Down
  claimLines: (npi: string, params: { hcpcs_code?: string; month?: string; page?: number; limit?: number }) =>
    get<ClaimLinesResponse>(`/providers/${npi}/claim-lines`, params as Record<string, string | number>),

  hcpcsDetail: (npi: string, code: string) =>
    get<HcpcsDetailResponse>(`/providers/${npi}/hcpcs/${code}/detail`),

  // ROI Dashboard
  roiSummary: () => get<ROISummary>('/roi/summary'),

  roiRecoveries: (params?: { page?: number; limit?: number }) =>
    get<{ items: RecoveryRecord[]; total: number; page: number; limit: number }>(
      '/roi/recoveries',
      params as Record<string, string | number>,
    ),

  logRecovery: (data: { npi: string; amount: number; recovery_type: string; notes?: string }) =>
    fetch('/api/roi/recovery', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to log recovery') })
      return r.json()
    }),

  deleteRecovery: (id: string) =>
    fetch(`/api/roi/recovery/${id}`, { method: 'DELETE', headers: { ...authHeaders() } }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to delete') })
      return r.json()
    }),

  // Exclusion Cross-Referencing
  exclusionSummary: (npi: string) => get<ExclusionSummary>(`/providers/${npi}/exclusion-summary`),

  batchExclusionScan: () =>
    fetch('/api/exclusions/scan-all', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()) as Promise<BatchExclusionResults>,

  batchExclusionResults: () => get<BatchExclusionResults>('/exclusions/summary'),

  // Billing Network Analysis
  billingNetwork: (npi: string) => get<BillingNetwork>(`/providers/${npi}/billing-network`),

  // Geographic Analysis
  geographyByZip: () =>
    get<{
      by_zip: {
        zip3: string
        provider_count: number
        total_paid: number
        flagged_count: number
        avg_risk_score: number
      }[]
    }>('/geography/by-zip'),

  geographyByCity: () =>
    get<{
      by_city: {
        city: string
        state: string
        provider_count: number
        total_paid: number
        flagged_count: number
        avg_risk_score: number
        top_npis: string[]
      }[]
    }>('/geography/by-city'),

  geographyHotspots: () =>
    get<{
      hotspots: {
        zip3: string
        provider_count: number
        total_paid: number
        flagged_count: number
        avg_risk_score: number
        states: string[]
        cities: string[]
        flagged_npis: string[]
        severity: 'CRITICAL' | 'HIGH' | 'WATCH'
      }[]
    }>('/geography/hotspots'),

  geographyStateDrilldown: (state: string) =>
    get<{
      state: string
      total_providers: number
      total_flagged: number
      total_paid: number
      cities: {
        city: string
        state: string
        provider_count: number
        total_paid: number
        flagged_count: number
        avg_risk_score: number
        top_npis: string[]
      }[]
    }>(`/geography/state/${state}`),

  // Data Sources (Multi-State)
  dataSources: () => get<DataSourcesResponse>('/data/sources'),

  addDataSource: (url: string, state?: string) =>
    fetch('/api/data/add-source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ url, state: state ?? null }),
    }).then(r => r.json()),

  removeDataSource: (path: string) =>
    fetch('/api/data/remove-source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ path }),
    }).then(r => r.json()),

  // Time-Series Forecasting
  providerForecast: (npi: string) => get<BillingForecast>(`/providers/${npi}/forecast`),

  // LLM Case Narratives
  providerNarrative: (npi: string) => get<{
    narrative: string
    sections: { title: string; content: string }[]
    generated_at: string
    word_count: number
  }>(`/providers/${npi}/narrative`),

  // Provider Timeline Analysis
  timelineAnalysis: (npi: string) => get<TimelineAnalysis>(`/providers/${npi}/timeline-analysis`),

  // Year-over-Year Temporal Analysis
  yoyComparison: (npi: string) => get<YoyComparison>(`/providers/${npi}/yoy-comparison`),

  // Related Provider Auto-Discovery
  relatedProviders: (npi: string) => get<RelatedProvidersResponse>(`/providers/${npi}/related`),

  // Demographic Risk Analysis
  demographicRiskMap: () => get<{
    states: DemographicState[]
    kpis: {
      states_elevated_risk: number
      highest_correlation_factor: string
      correlation_value: number
      national_avg_demographic_risk: number
    }
  }>('/demographics/risk-map'),

  demographicCorrelations: () => get<{
    correlations: DemographicCorrelation[]
  }>('/demographics/correlations'),

  demographicStateDetail: (state: string) => get<DemographicStateDetail>(`/demographics/state/${state}`),

  // Fraud Hotspot Analysis
  hotspotsComposite: () => get<{
    total_areas: number
    severity_counts: Record<string, number>
    hotspots: HotspotArea[]
  }>('/hotspots/composite'),

  hotspotsTop: (limit = 20) => get<{
    total_areas: number
    hotspots: HotspotAreaDetail[]
  }>('/hotspots/top', { limit }),

  hotspotZip: (zip3: string) => get<HotspotAreaDetail>(`/hotspots/zip/${zip3}`),

  // Beneficiary Density
  beneficiaryDensity: () => get<{states: any[]; national_avg_billing_per_enrollee: number; total_enrollment: number; flagged_count: number}>('/beneficiary/density'),
  beneficiaryDensityState: (state: string) => get<any>(`/beneficiary/density/${state}`),

  // Utilization Analysis
  utilizationByState: () => get<{
    states: {
      state: string
      enrollment: number
      total_claims: number
      total_beneficiaries: number
      total_paid: number
      provider_count: number
      claims_per_1000: number
      national_avg_claims_per_1000: number
      deviation_pct: number
      flagged: boolean
    }[]
    total_states: number
    flagged_states: number
  }>('/utilization/by-state'),

  utilizationOutliers: (limit = 50) => get<{
    outliers: {
      npi: string
      provider_name: string
      state: string
      specialty: string
      total_claims: number
      total_paid: number
      expected_claims: number
      state_specialty_avg: number
      deviation_multiple: number
      peer_count: number
      risk_score: number
    }[]
    total: number
    limit: number
  }>('/utilization/outliers', { limit }),

  utilizationStateDetail: (state: string) => get<{
    state: string
    providers: {
      npi: string
      provider_name: string
      specialty: string
      total_claims: number
      total_paid: number
      total_beneficiaries: number
      claims_per_1000: number
      actual_share_pct: number
      expected_share_pct: number
      share_ratio: number
      risk_score: number
    }[]
    total: number
  }>(`/utilization/state/${state}`),

  // Population Ratio Analysis
  populationRatios: () => get<{
    states: {
      state: string
      provider_count: number
      enrollment: number
      providers_per_100k: number
      national_avg_per_100k: number
      ratio_vs_national: number
      flagged: boolean
      total_paid: number
      avg_risk_score: number
    }[]
    national_avg_per_100k: number
    total_providers: number
    total_enrollment: number
  }>('/population/ratios'),

  populationOvercapacity: () => get<{
    providers: {
      npi: string
      provider_name: string
      state: string
      specialty: string
      total_paid: number
      estimated_max: number
      overage_amount: number
      overage_pct: number
      total_claims: number
      total_beneficiaries: number
      risk_score: number
    }[]
    total: number
  }>('/population/overcapacity'),

  populationStateZips: (state: string) => get<{
    state: string
    zips: {
      zip_prefix: string
      provider_count: number
      total_paid: number
      avg_risk_score: number
      ratio_vs_state_avg: number
      flagged: boolean
    }[]
    state_avg_per_zip: number
    enrollment: number
  }>(`/population/state/${state}/zips`),

  // State Enrollment Trends vs Billing Growth
  trendDivergence: () => get<{
    summary: {
      total_states: number
      states_with_data: number
      states_flagged: number
      largest_divergence_state: string | null
      largest_divergence_score: number
      avg_billing_growth_pct: number
      avg_enrollment_growth_pct: number
    }
    states: TrendState[]
  }>('/trends/divergence'),

  trendStateDetail: (state: string) => get<TrendState>(`/trends/state/${state}`),

  // Provider Watchlist
  watchlist: () => get<WatchlistResponse>('/watchlist'),

  watchlistAlerts: () => get<WatchlistAlertsResponse>('/watchlist/alerts'),

  watchlistCheck: (npi: string) => get<{ npi: string; watched: boolean }>(`/watchlist/check/${npi}`),

  addToWatchlist: (data: { npi: string; reason?: string; alert_threshold?: number; notes?: string }) =>
    fetch('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to add to watchlist') })
      return r.json() as Promise<WatchlistEntry>
    }),

  removeFromWatchlist: (npi: string) =>
    fetch(`/api/watchlist/${npi}`, { method: 'DELETE', headers: { ...authHeaders() } }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to remove') })
      return r.json()
    }),

  updateWatchlist: (npi: string, data: { notes?: string; alert_threshold?: number; active?: boolean; reason?: string }) =>
    fetch(`/api/watchlist/${npi}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to update') })
      return r.json() as Promise<WatchlistEntry>
    }),

  // Specialty Benchmarking
  specialtyList: () => get<{ specialties: SpecialtyListItem[]; total: number }>('/specialty/list'),

  specialtyStats: (specialty: string) => get<SpecialtyStats>(`/specialty/${encodeURIComponent(specialty)}/stats`),

  specialtyOutliers: (specialty: string, limit = 20) =>
    get<{ specialty: string; mean_paid: number; std_dev: number; provider_count: number; outliers: SpecialtyOutlier[] }>(
      `/specialty/${encodeURIComponent(specialty)}/outliers`,
      { limit },
    ),

  providerSpecialtyRank: (npi: string) => get<SpecialtyRank>(`/specialty/provider/${npi}/rank`),

  // Medicare Cross-Reference
  medicareUtilization: (npi: string) => get<MedicareUtilization>(`/providers/${npi}/medicare`),

  medicareCompare: (npi: string) => get<MedicareComparison>(`/providers/${npi}/medicare-compare`),

  // Score Trend Tracking
  scoreTrend: (npi: string) => get<ScoreTrendResponse>(`/score-trends/${npi}`),

  scoreMovers: (top = 10) => get<ScoreMoversResponse>('/score-trends/movers/list', { top }),

  scoreSummary: () => get<ScoreSummaryResponse>('/score-trends/summary/distribution'),

  // Fraud Ring Detection
  fraudRings: () => get<FraudRingsResponse>('/rings'),

  fraudRingDetail: (ringId: string) => get<FraudRingDetail>(`/rings/${ringId}`),

  detectRings: () =>
    fetch('/api/rings/detect', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()) as Promise<{ status: string; rings_found: number; total_providers_in_rings: number }>,

  // Temporal Anomaly Detection
  temporalAnalysis: (npi: string) => get<TemporalAnalysis>(`/temporal/providers/${npi}`),

  systemTemporalPatterns: () => get<SystemTemporalPatterns>('/temporal/system-patterns'),

  // News & Legal Alerts
  newsAlerts: (params?: {
    category?: string
    severity?: string
    date_from?: string
    date_to?: string
    search?: string
  }) => get<NewsAlertsResponse>('/news', params as Record<string, string>),

  providerNews: (npi: string) => get<{ npi: string; alerts: NewsAlert[]; total: number }>(`/providers/${npi}/news`),

  createNewsAlert: (data: {
    title: string
    source: string
    url: string
    category: string
    summary: string
    severity?: string
    npi?: string
    date?: string
  }) =>
    fetch('/api/news', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => r.json()) as Promise<{ ok: boolean; alert: NewsAlert }>,

  deleteNewsAlert: (id: string) =>
    fetch(`/api/news/${id}`, { method: 'DELETE', headers: { ...authHeaders() } }).then(r => r.json()) as Promise<{ ok: boolean }>,

  scanHhsNews: () =>
    fetch('/api/news/scan-hhs', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()) as Promise<{ ok: boolean; fetched: number; message: string }>,

  // License & Credential Verification
  providerLicense: (npi: string) => get<LicenseVerification>(`/license/providers/${npi}`),

  licenseFlags: () => get<LicenseFlagsResponse>('/license/flags'),

  // Beneficiary Fraud Detection
  beneficiaryFraudSummary: () => get<BeneficiaryFraudSummary>('/beneficiary-fraud/summary'),

  beneficiaryFraudDoctorShopping: (limit = 100) =>
    get<BeneficiaryFraudResult>('/beneficiary-fraud/doctor-shopping', { limit }),

  beneficiaryFraudHighUtilization: (limit = 100) =>
    get<BeneficiaryFraudResult>('/beneficiary-fraud/high-utilization', { limit }),

  beneficiaryFraudGeographic: (limit = 100) =>
    get<BeneficiaryFraudResult>('/beneficiary-fraud/geographic-anomalies', { limit }),

  beneficiaryFraudExcessive: (limit = 100) =>
    get<BeneficiaryFraudResult>('/beneficiary-fraud/excessive-services', { limit }),

  beneficiaryFraudProvider: (npi: string) =>
    get<BeneficiaryFraudProviderResult>(`/beneficiary-fraud/provider/${npi}`),

  // Pharmacy / Drug Fraud
  pharmacyHighRisk: (limit = 50) =>
    get<PharmacyHighRiskResponse>('/pharmacy/high-risk', { limit }),

  pharmacyProvider: (npi: string) =>
    get<PharmacyProviderDetail>(`/pharmacy/provider/${npi}`),

  // DME Fraud
  dmeHighRisk: (limit = 50) =>
    get<DMEHighRiskResponse>('/dme/high-risk', { limit }),

  dmeProvider: (npi: string) =>
    get<DMEProviderDetail>(`/dme/provider/${npi}`),

  // Claim-Level Fraud Patterns
  claimPatternSummary: () => get<any>('/claim-patterns/summary'),

  claimPatternUnbundling: (limit = 100) =>
    get<any>('/claim-patterns/unbundling', { limit }),

  claimPatternDuplicates: (limit = 100) =>
    get<any>('/claim-patterns/duplicates', { limit }),

  claimPatternPos: (limit = 100) =>
    get<any>('/claim-patterns/place-of-service', { limit }),

  claimPatternModifiers: (limit = 100) =>
    get<any>('/claim-patterns/modifiers', { limit }),

  claimPatternImpossible: (limit = 100) =>
    get<any>('/claim-patterns/impossible-days', { limit }),

  claimPatternProvider: (npi: string) =>
    get<any>(`/claim-patterns/provider/${npi}`),

  // Supervised ML Model
  supervisedTrain: () =>
    fetch('/api/ml/supervised/train', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  supervisedStatus: () =>
    get<any>('/ml/supervised/status'),

  supervisedFeatureImportance: () =>
    get<any>('/ml/supervised/feature-importance'),

  supervisedPredict: (npi: string) =>
    get<any>(`/ml/supervised/predict/${npi}`),

  supervisedPredictions: (limit = 50, offset = 0) =>
    get<any>('/ml/supervised/predictions', { limit, offset }),

  // ── Integration: MMIS ──────────────────────────────────────────────────────
  mmisStatus: () => get<MMISStatus>('/integrations/mmis/status'),

  mmisEligibility: (beneId: string) =>
    get<MMISEligibility>(`/integrations/mmis/eligibility/${beneId}`),

  mmisEnrollment: (npi: string) =>
    get<MMISEnrollment>(`/integrations/mmis/enrollment/${npi}`),

  // ── Integration: NPPES Bulk ────────────────────────────────────────────────
  nppesBulkStatus: () => get<NPPESBulkStatus>('/admin/nppes-bulk-status'),

  nppesBulkRefresh: () =>
    fetch('/api/admin/nppes-bulk-refresh', {
      method: 'POST',
      headers: authHeaders(),
    }).then(r => r.json()),

  // ── Integration: DEA ──────────────────────────────────────────────────────
  providerDea: (npi: string) => get<DEAStatus>(`/providers/${npi}/dea`),

  // ── Integration: Email/SMTP ───────────────────────────────────────────────
  emailStatus: () => get<SMTPStatus>('/admin/email/status'),

  emailTest: (to: string) =>
    fetch('/api/admin/email/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ to }),
    }).then(r => r.json()),

  // ── Integration: FHIR Export ──────────────────────────────────────────────
  providerFhir: (npi: string) => get<FHIRPractitioner>(`/providers/${npi}/fhir`),

  providerFhirReport: (npi: string) =>
    get<FHIRDocumentReference>(`/providers/${npi}/fhir/report`),

  // ── Data Pipeline Admin ──────────────────────────────────────────────────
  datasetInfo: () => get<{
    url: string
    detected_date: string | null
    row_count: number | null
    last_checked: number | null
    active_path: string
    is_local: boolean
    configured_url: string
  }>('/admin/dataset-info'),

  datasetRefresh: () =>
    fetch('/api/admin/dataset-refresh', { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()) as Promise<{
      checked_at: number
      current_url: string
      current_date: string | null
      new_url: string | null
      new_date: string | null
      update_available: boolean
      message: string
    }>,

  datasetSwitch: (url: string) =>
    fetch('/api/admin/dataset-switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }).then(r => r.json()),

  dataQuality: () => get<{
    last_run: number | null
    status: string
    total_dataset_rows: number
    sample_size: number
    valid_records: number
    invalid_records: number
    quality_score: number
    failures: Record<string, number>
    summary: {
      npi_issues: number
      amount_issues: number
      date_issues: number
      high_value_claims: number
    }
  }>('/admin/data-quality'),

  runDataQuality: (sampleLimit = 5000) =>
    fetch(`/api/admin/data-quality/run?sample_limit=${sampleLimit}`, { method: 'POST', headers: { ...authHeaders() } }).then(r => r.json()),

  dataLineage: (page = 1, limit = 50) => get<{
    entries: {
      id: number
      timestamp: number
      dataset_url: string
      dataset_date: string | null
      scan_type: string
      provider_count: number
      total_claims: number
      duration_sec: number | null
      state_filter: string | null
      details: Record<string, unknown> | null
    }[]
    total: number
    page: number
    limit: number
    summary: {
      total_scans: number
      dataset_versions_seen: number
      latest_scan: number | null
      earliest_scan: number | null
    }
  }>('/admin/lineage', { page, limit }),

  // PHI Access Log
  phiLog: (params?: { user_id?: string; resource_type?: string; resource_id?: string; page?: number; limit?: number }) =>
    get<PHILogResponse>('/admin/phi-log', params as Record<string, string | number>),

  phiLogStats: () => get<PHILogStats>('/admin/phi-log/stats'),

  // Data Retention
  retentionStatus: () => get<RetentionStatus>('/admin/retention'),

  retentionPolicy: () => get<{ policies: RetentionPolicy[] }>('/admin/retention/policy'),

  enforceRetention: () =>
    fetch('/api/admin/retention/enforce', {
      method: 'POST',
      headers: { ...authHeaders() },
    }).then(r => r.json()),

  // Evidence Chain of Custody
  uploadEvidence: (caseId: string, file: File, description?: string, evidenceType?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (description) formData.append('description', description)
    if (evidenceType) formData.append('evidence_type', evidenceType)
    return fetch(`/api/cases/${caseId}/evidence`, {
      method: 'POST',
      headers: { ...authHeaders() },
      body: formData,
    }).then(r => r.json()) as Promise<EvidenceRecord>
  },

  listEvidence: (caseId: string) =>
    get<EvidenceListResponse>(`/cases/${caseId}/evidence`),

  downloadEvidence: (caseId: string, evidenceId: string) => {
    const a = document.createElement('a')
    a.href = `/api/cases/${caseId}/evidence/${evidenceId}/download`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  },

  verifyEvidence: (caseId: string, evidenceId: string) =>
    get<{ valid: boolean; original_hash: string; current_hash: string; evidence_id: string }>(`/cases/${caseId}/evidence/${evidenceId}/verify`),

  evidenceCustody: (caseId: string, evidenceId: string) =>
    get<{ evidence_id: string; case_id: string; original_filename: string; sha256_hash: string; chain_of_custody: { action: string; by: string; timestamp: number }[] }>(`/cases/${caseId}/evidence/${evidenceId}/custody`),

  // MFCU Referral Workflow
  submitReferral: (npi: string, data: { mfcu_contact?: string; jurisdiction?: string; case_number?: string; notes?: string }) =>
    fetch(`/api/referrals/${npi}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to submit referral') })
      return r.json() as Promise<MFCUReferral>
    }),

  listReferrals: (params?: { stage?: string; npi?: string }) =>
    get<ReferralsResponse>('/referrals', params as Record<string, string>),

  getReferral: (id: number) => get<MFCUReferral>(`/referrals/${id}`),

  getProviderReferrals: (npi: string) =>
    get<{ npi: string; referrals: MFCUReferral[]; total: number }>(`/referrals/provider/${npi}`),

  updateReferral: (id: number, data: { stage?: string; outcome?: string; outcome_notes?: string; mfcu_contact?: string; case_number?: string; jurisdiction?: string; notes?: string }) =>
    fetch(`/api/referrals/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    }).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed to update referral') })
      return r.json() as Promise<MFCUReferral>
    }),

  referralStats: () => get<ReferralStats>('/referrals/stats/summary'),

  referralStages: () => get<{ stages: string[] }>('/referrals/meta/stages'),

  referralOutcomes: () => get<{ outcomes: string[] }>('/referrals/meta/outcomes'),
}

// ── Demographic Risk types ──────────────────────────────────────────────────
export interface DemographicState {
  state: string
  population: number
  poverty_rate: number
  median_income: number
  pct_uninsured: number
  medicaid_pct: number
  provider_count: number
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  avg_risk_score: number
  billing_per_capita: number
  demographic_risk_score: number
}

export interface DemographicCorrelation {
  state: string
  poverty_rate: number
  avg_risk_score: number
  provider_count: number
  median_income: number
  medicaid_pct: number
  demographic_risk_score: number
}

export interface DemographicStateDetail extends DemographicState {
  providers: {
    npi: string
    provider_name: string
    city: string
    total_paid: number
    total_claims: number
    risk_score: number
    flag_count: number
  }[]
  providers_total: number
}

// ── Hotspot types ──────────────────────────────────────────────────────────
export interface HotspotComponents {
  avg_risk: number
  flagged_pct: number
  billing_concentration: number
  density_anomaly: number
  high_risk_count: number
}

export interface HotspotArea {
  zip3: string
  composite_score: number
  severity: string
  provider_count: number
  flagged_count: number
  flagged_pct: number
  high_risk_count: number
  avg_risk_score: number
  total_billing: number
  billing_concentration: number
  density_ratio: number
  states: string[]
  cities: string[]
  components: HotspotComponents
}

export interface HotspotProvider {
  npi: string
  provider_name: string
  risk_score: number
  total_paid: number
  total_claims: number
  flag_count: number
  state: string
  city: string
}

export interface HotspotAreaDetail extends HotspotArea {
  top_providers: HotspotProvider[]
}

// ── Trend Divergence types ──────────────────────────────────────────────────
export interface TrendYearly {
  year: number
  enrollment_millions: number
  total_billing: number
  billing_per_enrollee: number
}

export interface TrendYoY {
  year: number
  enrollment_change_pct: number
  billing_change_pct: number
  divergence_pct: number
  is_divergent: boolean
}

export interface TrendState {
  state: string
  has_billing_data: boolean
  enrollment_trend: 'up' | 'down' | 'flat'
  billing_trend: 'up' | 'down' | 'flat'
  divergence_score: number
  consecutive_divergent_years: number
  flagged: boolean
  yearly: TrendYearly[]
  yoy: TrendYoY[]
}

// ── Beneficiary Fraud Detection types ──────────────────────────────────────
export interface BeneficiaryFraudSummary {
  total_providers_analyzed: number
  total_beneficiary_records: number
  total_paid: number
  has_individual_bene_id: boolean
  flagged_counts: {
    doctor_shopping: number
    high_utilization: number
    geographic_anomalies: number
    excessive_services: number
  }
  note: string
}

export interface BeneficiaryFraudResult {
  flagged: Record<string, any>[]
  total_flagged: number
  note?: string
  error?: string
}

export interface BeneficiaryFraudProviderFlag {
  type: string
  severity: string
  description: string
}

export interface BeneficiaryFraudProviderResult {
  npi: string
  found: boolean
  provider_stats?: {
    total_paid: number
    total_claims: number
    total_benes: number
    distinct_hcpcs: number
    active_months: number
    claims_per_bene: number
    rev_per_bene: number
  }
  peer_comparison?: Record<string, number>
  code_overlap?: { hcpcs_code: string; other_providers: number }[]
  flags?: BeneficiaryFraudProviderFlag[]
  flag_count?: number
  error?: string
  note?: string
}
