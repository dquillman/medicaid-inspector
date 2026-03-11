export interface ProviderAggregate {
  npi: string
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  distinct_hcpcs: number
  active_months: number
  first_month: string
  last_month: string
  revenue_per_beneficiary: number
  claims_per_beneficiary: number
  // enriched from NPPES
  state?: string
  city?: string
  provider_name?: string
}

export interface SignalResult {
  signal: string
  score: number
  weight: number
  reason: string
  flagged: boolean
}

export interface ScoredProvider extends ProviderAggregate {
  risk_score: number
  flags: SignalResult[]
  signal_results: SignalResult[]
  // Optionally enriched from review queue
  review_status?: 'pending' | 'assigned' | 'investigating' | 'confirmed_fraud' | 'referred' | 'dismissed'
  review_notes?: string
}

export interface NppesAddress {
  line1: string
  line2: string
  city: string
  state: string
  zip: string
}

export interface NppesTaxonomy {
  code: string
  description: string
  license: string
}

export interface NppesData {
  npi: string
  entity_type: string
  name: string
  status: string
  address: NppesAddress
  taxonomy: NppesTaxonomy
  authorized_official: { name: string; title: string } | null
  last_updated: string
}

export interface ProviderDetail extends ScoredProvider {
  nppes: NppesData
  spending: ProviderAggregate
}

export interface TimelineRow {
  month: string
  total_paid: number
  total_claims: number
  total_unique_beneficiaries: number
}

export interface HcpcsRow {
  hcpcs_code: string
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  description?: string
}

export interface NetworkNode {
  id: string
  total_paid: number
  is_center: boolean
  risk_score?: number
}

export interface NetworkEdge {
  source: string
  target: string
  weight: number
  claim_count: number
  type: string
}

export interface NetworkGraph {
  center_npi: string
  nodes: NetworkNode[]
  edges: NetworkEdge[]
}

export interface ScanProgress {
  offset: number
  total_provider_count: number | null
  state_filter: string | null
  batches_completed: number
  last_batch_at: number | null
}

export interface PrescanStatus {
  phase: number
  message: string
  elapsed_sec: number
  scan_progress: ScanProgress | null
  auto_mode?: boolean
  smart_scan_mode?: boolean
}

export interface Summary {
  total_providers: number
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  flagged_providers: number   // score > review threshold (10)
  high_risk_providers: number // score >= 50
  avg_risk_score: number
  prescan_complete: boolean
  note?: string
}

export interface SignalSummary {
  signal: string
  count: number
}

export interface AuditEntry {
  action: string
  previous_status: string
  new_status: string
  timestamp: number
  note?: string
}

export interface ReviewItem {
  npi: string
  risk_score: number
  flags: SignalResult[]
  signal_results: SignalResult[]
  total_paid: number
  total_claims: number
  status: 'pending' | 'assigned' | 'investigating' | 'confirmed_fraud' | 'referred' | 'dismissed'
  notes: string
  assigned_to?: string | null
  added_at: number
  updated_at: number
  audit_trail?: AuditEntry[]
  // Enriched from prescan cache
  provider_name?: string
  state?: string
}

export interface OigStatus {
  npi: string
  excluded: boolean
  record: {
    name: string
    busname: string
    specialty: string
    excl_type: string
    excl_date: string
    state: string
  } | null
  loaded: boolean
  record_count: number
}

export interface ClusterProvider {
  npi: string
  provider_name: string
  risk_score: number
  total_paid: number
  flag_count: number
  specialty: string
}

export interface AddressCluster {
  npi: string
  address: { line1: string; city: string; state: string; zip: string }
  cluster: ClusterProvider[]
  cluster_count: number
}

export interface PeerStats {
  mean: number
  median: number
  p75: number
  p90: number
  p95: number | null
  count: number
}

export interface ProviderPeers {
  npi: string
  top_hcpcs: string | null
  peer_count: number
  this_provider: {
    revenue_per_beneficiary: number
    claims_per_beneficiary: number
    total_paid: number
  }
  rpb_stats: PeerStats | null
  cpb_stats: PeerStats | null
  paid_stats: PeerStats | null
  percentiles: {
    revenue_per_beneficiary: number | null
    claims_per_beneficiary: number | null
    total_paid: number | null
  }
}

export interface ReviewCounts {
  pending: number
  assigned: number
  investigating: number
  confirmed_fraud: number
  referred: number
  dismissed: number
  total: number
}

export interface OpenPaymentsData {
  has_payments: boolean
  payment_count: number
  total_amount: number
  unique_companies: string[]
  records: Record<string, unknown>[]
  error?: string
}

export interface SamExclusion {
  excluded: boolean
  records: Record<string, unknown>[]
  error?: string
}

// Alert Rules Engine
export interface AlertCondition {
  field: string
  operator: string
  value: number
}

export interface AlertRule {
  id: string
  name: string
  conditions: AlertCondition[]
  enabled: boolean
  created_at: number
}

export interface AlertMatchProvider {
  npi: string
  provider_name: string
  state: string
  risk_score: number
  total_paid: number
  flag_count: number
}

export interface AlertRuleResult {
  rule: AlertRule
  matching_providers: AlertMatchProvider[]
  match_count: number
}

// Case Management
export interface CaseDocument {
  id: string
  filename: string
  uploaded_at: number
  description: string
  data_type: string
}

export interface CaseStats {
  total_cases: number
  by_status: Record<string, number>
  by_priority: Record<string, number>
  total_hours_logged: number
  avg_resolution_hours: number
  resolved_cases: number
  overdue_count: number
}

// Audit Log
export interface AuditLogEntry {
  id: number
  timestamp: number
  action_type: string
  entity_type: string
  entity_id: string
  user: string
  details: Record<string, unknown> | null
  ip_address: string | null
}

export interface AuditLogResponse {
  entries: AuditLogEntry[]
  total: number
  page: number
  limit: number
}

export interface AuditStats {
  total_entries: number
  by_action_type: Record<string, number>
  actions_per_day: { date: string; count: number }[]
  most_active_entities: { entity: string; count: number }[]
}

// Peer Distribution
export interface DistributionBucket {
  min: number
  max: number
  count: number
}

export interface MetricDistribution {
  metric: string
  label: string
  buckets: DistributionBucket[]
  provider_value: number
  percentile: number
  peer_count: number
}

export interface PeerDistribution {
  npi: string
  top_hcpcs: string | null
  peer_count: number
  distributions: MetricDistribution[]
}

// Ownership Chain
export interface OwnershipNpi {
  npi: string
  name: string
  entity_type: string
  risk_score: number
  total_paid: number
  flag_count: number
  address: { line1: string; city: string; state: string; zip: string }
  specialty: string
  status?: string
}

export interface OwnershipChain {
  official: { name: string; title: string } | null
  controlled_npis: OwnershipNpi[]
  total_entities: number
  total_combined_billing: number
  shared_addresses: { address: string; npis: string[] }[]
}

export interface OwnershipNetworkEntry {
  official_name: string
  npi_count: number
  total_billing: number
  avg_risk_score: number
  top_risk_npi: { npi: string; name: string; risk_score: number }
  npis: OwnershipNpi[]
}

export interface OwnershipNetworksResponse {
  networks: OwnershipNetworkEntry[]
  total_networks: number
}

// Claim-Level Drill-Down
export interface ClaimLine {
  billing_npi: string
  servicing_npi: string
  hcpcs_code: string
  month: string
  beneficiaries: number
  claims: number
  paid: number
}

export interface ClaimLinesResponse {
  npi: string
  claim_lines: ClaimLine[]
  page: number
  limit: number
  total: number
}

export interface HcpcsMonthlyRow {
  month: string
  claims: number
  paid: number
  beneficiaries: number
  servicing_npi: string
}

export interface HcpcsDetailResponse {
  npi: string
  hcpcs_code: string
  description: string
  monthly: HcpcsMonthlyRow[]
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  pct_of_total: number
  avg_paid_per_month: number
  avg_claims_per_month: number
  month_count: number
}

// ROI Dashboard
export interface RecoveryRecord {
  id: string
  npi: string
  amount_recovered: number
  recovery_date: string
  recovery_type: string
  notes: string
  created_at: number
}

export interface ROISummary {
  total_recovered: number
  total_flagged_billing: number
  recovery_rate: number
  cases_confirmed: number
  cases_referred: number
  cases_dismissed: number
  false_positive_rate: number
  avg_time_to_resolution: number
  monthly_trend: { month: string; amount: number }[]
  top_recoveries: RecoveryRecord[]
}

// Exclusion Cross-Referencing
export interface ExclusionCheck {
  source: string
  status: 'clear' | 'excluded' | 'warning' | 'unavailable' | 'error'
  details: Record<string, unknown>
}

export interface ExclusionSummary {
  npi: string
  checks: ExclusionCheck[]
  any_excluded: boolean
  risk_level: 'clear' | 'warning' | 'excluded'
}

export interface ExcludedProvider {
  npi: string
  provider_name: string
  state: string
  risk_score: number
  issues: string[]
  oig_excluded: boolean
  oig_record: Record<string, unknown> | null
}

export interface BatchExclusionResults {
  total_checked: number
  oig_excluded_count: number
  deactivated_count: number
  new_npi_count: number
  total_excluded: number
  oig_list_loaded: boolean
  oig_list_size: number
  excluded_providers: ExcludedProvider[]
  scanned_at: string | null
  never_scanned?: boolean
}

// Billing Network Analysis
export interface BillingNetworkConnection {
  npi: string
  relationship: 'servicing' | 'billing'
  total_paid: number
  total_claims: number
  distinct_hcpcs: number
  provider_name: string
  risk_score: number | null
  oig_excluded: boolean
}

export interface BillingNetwork {
  npi: string
  connections: BillingNetworkConnection[]
  servicing_count: number
  billing_count: number
  total_connections: number
}

// Multi-State Data Sources
export interface DataSourceEntry {
  path: string
  state: string | null
  size_mb: number
  status: 'available' | 'unavailable' | 'remote' | 'unknown'
  filename: string
  row_count: number | null
}

export interface DataSourcesResponse {
  sources: DataSourceEntry[]
  total_sources: number
}

// Time-Series Forecasting
export interface ForecastMonth {
  month: string
  predicted_paid: number
  lower_bound: number
  upper_bound: number
}

export interface BillingForecast {
  npi: string
  forecasted_months: ForecastMonth[]
  last_actual: number
  spike_detected: boolean
  spike_magnitude: number
}

// Provider Timeline Analysis
export interface TimelineMonth {
  month: string
  total_paid: number
  claim_count: number
  unique_hcpcs_count: number
  unique_beneficiaries: number
  is_spike: boolean
  avg_paid: number
}

export interface TimelineEvent {
  type: 'first_billing' | 'last_billing' | 'spike' | 'gap'
  month: string
  description: string
  total_paid?: number
  multiple?: number
  gap_months?: number
  gap_start?: string
  gap_end?: string
}

export interface TimelineSummary {
  total_months: number
  avg_monthly_paid: number
  max_monthly_paid: number
  spike_count: number
  gap_count: number
}

export interface TimelineAnalysis {
  npi: string
  months: TimelineMonth[]
  events: TimelineEvent[]
  summary: TimelineSummary
}

// Related Provider Auto-Discovery
export interface RelatedProvider {
  npi: string
  name: string
  specialty: string
  state: string
  city: string
  relationship_types: string[]
  relationship_type: string
  strength_score: number
  shared_count: number
  risk_score: number
  total_paid: number
}

export interface RelatedProvidersResponse {
  npi: string
  related_providers: RelatedProvider[]
  total: number
}

// Year-over-Year Temporal Analysis
export interface YoyYear {
  year: string
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  distinct_hcpcs: number
  pct_change_paid: number | null
  pct_change_claims: number | null
  pct_change_beneficiaries: number | null
  flagged: boolean
}

export interface YoyComparison {
  npi: string
  years: YoyYear[]
}

// Provider Watchlist
export interface WatchlistEntry {
  npi: string
  name: string
  specialty: string
  added_date: number
  reason: string
  alert_threshold: number
  notes: string
  active: boolean
  risk_score: number | null
  total_paid: number | null
  total_claims: number | null
  flag_count: number | null
  state?: string
  city?: string
  in_alert: boolean
}

export interface WatchlistResponse {
  items: WatchlistEntry[]
  total: number
  alert_count: number
}

export interface WatchlistAlertsResponse {
  alerts: WatchlistEntry[]
  total: number
}

// Specialty Benchmarking
export interface SpecialtyListItem {
  specialty: string
  provider_count: number
  total_paid: number
  avg_risk_score: number
}

export interface SpecialtyStats {
  specialty: string
  provider_count: number
  avg_paid_per_provider: number
  median_paid: number
  std_dev: number
  p25: number
  p75: number
  p90: number
  p95: number
  avg_claims_per_provider: number
  median_claims: number
  avg_beneficiaries: number
  median_beneficiaries: number
  top_hcpcs: { code: string; total_paid: number }[]
}

export interface SpecialtyOutlier {
  npi: string
  provider_name: string
  state: string
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  risk_score: number
  z_score: number
  deviation_from_mean: number
}

export interface SpecialtyRank {
  npi: string
  specialty: string
  provider_count: number
  note?: string
  this_provider?: {
    total_paid: number
    total_claims: number
    total_beneficiaries: number
  }
  percentiles?: {
    total_paid: number
    total_claims: number
    total_beneficiaries: number
  }
  stats?: {
    avg_paid: number
    median_paid: number
    p75_paid: number
    p90_paid: number
    p95_paid: number
    avg_claims: number
    median_claims: number
    p75_claims: number
    p90_claims: number
    median_beneficiaries: number
    p75_beneficiaries: number
    p90_beneficiaries: number
  }
}

// Medicare Cross-Reference
export interface MedicareHcpcs {
  hcpcs_code: string
  description: string
  total_paid: number
  total_services: number
  total_beneficiaries: number
}

export interface MedicareUtilization {
  npi: string
  has_data: boolean
  medicare_total_submitted: number
  medicare_total_paid: number
  medicare_beneficiaries: number
  medicare_total_services: number
  medicare_avg_per_bene: number
  top_hcpcs: MedicareHcpcs[]
  provider_type: string | null
  hcpcs_count?: number
  error?: string
}

export interface MedicareDiscrepancy {
  type: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  description: string
  medicaid_value: number
  medicare_value: number
  ratio: number | null
}

export interface MedicareCompareProgram {
  total_paid: number
  total_claims?: number
  total_services?: number
  total_submitted?: number
  total_beneficiaries: number
  avg_per_bene: number
  top_hcpcs: (MedicareHcpcs | { hcpcs_code: string; total_paid: number; total_claims: number })[]
  provider_type?: string | null
}

export interface MedicareComparison {
  npi: string
  medicare_has_data: boolean
  medicaid: MedicareCompareProgram
  medicare: MedicareCompareProgram
  discrepancies: MedicareDiscrepancy[]
  discrepancy_count: number
  has_discrepancies: boolean
  error?: string
}

// Fraud Ring Detection
export interface FraudRingSummary {
  ring_id: string
  member_count: number
  total_paid: number
  avg_risk_score: number
  high_risk_count: number
  total_flags: number
  density: number
  suspicion_score: number
  connection_types: string[]
}

export interface FraudRingMember {
  npi: string
  provider_name: string
  risk_score: number
  total_paid: number
  total_claims: number
  flag_count: number
  state: string
  city: string
}

export interface FraudRingEdge {
  source: string
  target: string
  type: string
  detail: string
}

export interface FraudRingDetail extends FraudRingSummary {
  members: FraudRingMember[]
  edges: FraudRingEdge[]
}

export interface FraudRingsResponse {
  rings: FraudRingSummary[]
  total: number
  detected: boolean
}

// Score Trend Tracking
export interface ScoreSnapshot {
  timestamp: number
  score: number
  flags: number
  total_paid: number
}

export interface ScoreTrendResponse {
  npi: string
  provider_name: string | null
  snapshots: ScoreSnapshot[]
  snapshot_count: number
}

export interface ScoreMover {
  npi: string
  provider_name: string
  previous_score: number
  current_score: number
  delta: number
  previous_timestamp: number
  current_timestamp: number
  current_flags: number
  total_paid: number
}

export interface ScoreMoversResponse {
  rising: ScoreMover[]
  falling: ScoreMover[]
}

export interface ScoreDistributionBucket {
  timestamp: number
  provider_count: number
  avg_score: number
  median_score: number
  high_risk_count: number
  flagged_count: number
}

export interface ScoreSummaryResponse {
  buckets: ScoreDistributionBucket[]
  total_providers: number
}

// Temporal Anomaly Detection
export interface TemporalDayDistribution {
  day: string
  estimated_claims: number
  percentage: number
  is_weekend: boolean
  is_anomalous: boolean
}

export interface TemporalMonthlyTrend {
  month: string
  total_paid: number
  total_claims: number
  total_beneficiaries: number
  distinct_hcpcs: number
  z_score_paid: number
  z_score_claims: number
  is_anomaly: boolean
  anomaly_type: string | null
}

export interface TemporalAnomaly {
  type: string
  date_range: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  description: string
  z_score: number
}

export interface ImpossibleDay {
  month: string
  total_claims: number
  business_days: number
  claims_per_day: number
  estimated_daily_hours: number
  total_paid: number
}

export interface TemporalAnalysis {
  npi: string
  day_of_week_distribution: TemporalDayDistribution[]
  monthly_trend: TemporalMonthlyTrend[]
  detected_anomalies: TemporalAnomaly[]
  impossible_days: ImpossibleDay[]
  summary: {
    total_months: number
    anomaly_count: number
    critical_count?: number
    high_count?: number
    mean_monthly_paid: number
    std_monthly_paid: number
  }
}

export interface SystemTemporalPatterns {
  monthly: {
    month: string
    total_paid: number
    total_claims: number
    active_providers: number
    total_beneficiaries: number
    z_score: number
    is_anomaly: boolean
  }[]
  seasonal_index: Record<string, number>
  summary: {
    total_months: number
    mean_monthly_paid: number
    std_monthly_paid: number
    anomalous_months: number
  }
}

// License & Credential Verification
export interface LicenseEntry {
  taxonomy_code: string
  taxonomy_description: string
  license_number: string
  state: string
  is_primary: boolean
  specialty_category: string
}

export interface TaxonomyCode {
  code: string
  description: string
  primary: boolean
}

export interface CredentialFlag {
  flag: string
  severity: 'critical' | 'warning' | 'info'
  title: string
  description: string
}

export interface TaxonomyMatch {
  taxonomy_match: boolean
  match_details: string
  mismatch_severity: string
  is_high_risk_taxonomy?: boolean
  primary_taxonomy?: string
  primary_specialty?: string
}

export interface DeactivationStatus {
  is_deactivated: boolean
  deactivation_date: string | null
  deactivation_reason: string | null
  npi_status: string
}

export interface EntityInfo {
  entity_type: string
  entity_type_label: string
  is_sole_proprietor: boolean
  is_individual: boolean
}

export interface LicenseVerification {
  npi: string
  verified: boolean
  error?: string
  enumeration_date?: string
  licenses: LicenseEntry[]
  taxonomy_codes: TaxonomyCode[]
  taxonomy_match: TaxonomyMatch | null
  deactivation_status: DeactivationStatus | null
  entity_info: EntityInfo | null
  credential_flags: CredentialFlag[]
  flag_count: number
  has_critical_flags: boolean
}

export interface LicenseFlaggedProvider {
  npi: string
  provider_name: string
  state: string
  risk_score: number
  total_paid: number
  credential_flags: CredentialFlag[]
  flag_count: number
  has_critical_flags: boolean
  deactivated: boolean
  entity_type: string
}

export interface LicenseFlagsResponse {
  flagged_providers: LicenseFlaggedProvider[]
  total_checked: number
  total_flagged: number
}

// News & Legal Alerts
export interface NewsAlert {
  id: string
  npi: string | null
  title: string
  source: string
  url: string
  date: string
  category: 'news' | 'legal' | 'enforcement' | 'settlement'
  summary: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  created_at: number
}

export interface NewsAlertsResponse {
  alerts: NewsAlert[]
  total: number
}

// Pharmacy / Drug Fraud
export interface PharmacyProviderFlag {
  npi: string
  provider_name: string
  state: string
  total_paid: number
  drug_paid: number
  drug_pct: number
  drug_code_count: number
  high_cost_pct: number
  controlled_pct: number
  unclassified_pct: number
  total_claims: number
  total_benes: number
  flags: string[]
  flag_count: number
  pharmacy_risk: number
  risk_score: number
}

export interface PharmacyKpis {
  total_drug_providers: number
  total_drug_billing: number
  avg_drug_pct: number
  flagged_count: number
  high_cost_count: number
  controlled_count: number
}

export interface PharmacyHighRiskResponse {
  available: boolean
  note?: string
  providers: PharmacyProviderFlag[]
  total: number
  kpis?: PharmacyKpis
}

export interface PharmacySignal {
  signal: string
  score: number
  severity: string
  description: string
  detail: Record<string, unknown>
}

export interface PharmacyDrugCode {
  code: string
  total_paid: number
  total_claims: number
  is_high_cost: boolean
  is_controlled: boolean
}

export interface PharmacyProviderDetail {
  npi: string
  available: boolean
  note?: string
  drug_billing_total: number
  drug_billing_pct: number
  total_paid: number
  drug_codes_used: number
  top_drug_codes: PharmacyDrugCode[]
  signals: PharmacySignal[]
  composite_risk: number
}

// DME Fraud
export interface DMEProviderFlag {
  npi: string
  provider_name: string
  state: string
  total_paid: number
  dme_paid: number
  dme_pct: number
  dme_code_count: number
  high_cost_pct: number
  dme_claims: number
  em_claims: number
  rental_pct: number
  z_score: number
  total_benes: number
  flags: string[]
  flag_count: number
  dme_risk: number
  risk_score: number
}

export interface DMEKpis {
  total_dme_providers: number
  total_dme_billing: number
  avg_dme_pct: number
  flagged_count: number
  high_cost_count: number
  no_em_count: number
}

export interface DMEHighRiskResponse {
  available: boolean
  note?: string
  providers: DMEProviderFlag[]
  total: number
  kpis?: DMEKpis
}

export interface DMESignal {
  signal: string
  score: number
  severity: string
  description: string
  detail: Record<string, unknown>
}

export interface DMECode {
  code: string
  total_paid: number
  total_claims: number
  is_high_cost: boolean
  is_rental_type: boolean
}

export interface DMEProviderDetail {
  npi: string
  available: boolean
  note?: string
  dme_billing_total: number
  dme_billing_pct: number
  total_paid: number
  dme_codes_used: number
  em_claims: number
  top_dme_codes: DMECode[]
  peer_comparison: {
    avg_dme_paid: number
    median_dme_paid: number
    peer_count: number
  }
  signals: DMESignal[]
  composite_risk: number
}

// MMIS Integration
export interface MMISStatus {
  configured: boolean
  endpoint_url: string | null
  has_api_key: boolean
  connection_status: string
  mode: string
  message: string
}

export interface MMISEligibility {
  bene_id: string
  eligible: boolean
  status: string
  plan: string
  effective_date: string
  end_date: string | null
  aid_category: string
  county: string
  managed_care_plan: string | null
  source: string
}

export interface MMISEnrollment {
  npi: string
  enrolled: boolean
  enrollment_status: string
  enrollment_date: string
  revalidation_due: string
  provider_type: string
  specialty: string
  accepts_new_patients: boolean
  sanctions: unknown[]
  source: string
}

// NPPES Bulk
export interface NPPESBulkStatus {
  last_refresh: string | null
  record_count: number
  cache_file: string
  cache_exists: boolean
  refresh_running: boolean
}

// DEA Cross-Reference
export interface DEAFlag {
  flag: string
  severity: 'critical' | 'warning' | 'info'
  title: string
  description: string
}

export interface DEAStatus {
  npi: string
  provider_name: string
  entity_type: string
  taxonomy: string
  likely_prescriber: boolean
  dea: {
    dea_number: string | null
    active: boolean | null
    schedules: string[]
    expiration_date: string | null
    registration_type: string | null
    note: string
  }
  flags: DEAFlag[]
  source: string
}

// Email/SMTP
export interface SMTPStatus {
  configured: boolean
  smtp_host: string | null
  smtp_port: number | null
  smtp_user: string | null
  from_email: string | null
  has_password: boolean
  status: string
  message: string
}

// FHIR Export
export interface FHIRPractitioner {
  resourceType: 'Practitioner'
  id: string
  meta: Record<string, unknown>
  identifier: { system: string; value: string }[]
  active: boolean
  name: { use: string; family: string; given: string[]; text: string }[]
  address?: Record<string, unknown>[]
  qualification?: Record<string, unknown>[]
  extension?: Record<string, unknown>[]
}

export interface FHIRDocumentReference {
  resourceType: 'DocumentReference'
  id: string
  meta: Record<string, unknown>
  status: string
  type: Record<string, unknown>
  subject: { reference: string; display: string }
  date: string
  content: Record<string, unknown>[]
  extension?: Record<string, unknown>[]
}

// PHI Access Log
export interface PHILogEntry {
  id: number
  timestamp: number
  user_id: string
  action: string
  resource_type: string
  resource_id: string
  ip_address: string | null
  details: Record<string, unknown> | null
}

export interface PHILogResponse {
  entries: PHILogEntry[]
  total: number
  page: number
  limit: number
}

export interface PHILogStats {
  total_entries: number
  by_resource_type: Record<string, number>
  by_user: Record<string, number>
  by_action: Record<string, number>
  accesses_per_day: { date: string; count: number }[]
  oldest_entry: number | null
  newest_entry: number | null
}

// Data Retention
export interface RetentionCategory {
  category: string
  record_count: number
  oldest_timestamp: number | null
  oldest_age_days: number | null
  retention_days: number | null
  retention_label: string
  needs_purge: boolean
}

export interface RetentionStatus {
  categories: RetentionCategory[]
  checked_at: number
  any_needs_purge: boolean
}

export interface RetentionPolicy {
  category: string
  retention_days: number | null
  retention_label: string
}

// Evidence Chain of Custody
export interface CustodyEvent {
  action: string
  by: string
  timestamp: number
  sha256_hash?: string
}

export interface EvidenceRecord {
  evidence_id: string
  case_id: string
  original_filename: string
  stored_filename: string
  sha256_hash: string
  file_size: number
  uploaded_by: string
  upload_timestamp: number
  description: string
  evidence_type: string
  chain_of_custody: CustodyEvent[]
}

export interface EvidenceListResponse {
  case_id: string
  evidence: EvidenceRecord[]
  total: number
}

// MFCU Referral Workflow
export interface ReferralHistoryEntry {
  stage: string
  timestamp: number
  by: string
  note: string
}

export interface MFCUReferral {
  id: number
  referral_id: string
  npi: string
  stage: 'draft' | 'submitted' | 'acknowledged' | 'under_investigation' | 'outcome_received'
  mfcu_contact: string
  jurisdiction: string
  case_number: string
  referral_date: number
  submitted_by: string
  outcome: string | null
  outcome_date: number | null
  outcome_notes: string
  notes: string
  created_at: number
  updated_at: number
  history: ReferralHistoryEntry[]
  // enriched
  provider_name?: string
  state?: string
  risk_score?: number
}

export interface ReferralsResponse {
  referrals: MFCUReferral[]
  total: number
}

export interface ReferralStats {
  total_referrals: number
  unique_providers: number
  by_stage: Record<string, number>
  by_outcome: Record<string, number>
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
  flagged: Record<string, unknown>[]
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

// ── Beneficiary Density types ───────────────────────────────────────────────
export interface BeneficiaryDensityState {
  state: string
  medicaid_enrollment: number
  provider_count: number
  total_billing: number
  total_claims: number
  billing_per_enrollee: number
  expected_billing_per_enrollee: number
  ratio: number
  flagged: boolean
}

export interface BeneficiaryDensityStateDetail {
  state: string
  medicaid_enrollment: number
  total_billing: number
  provider_count: number
  billing_per_enrollee: number
  cities: {
    city: string
    provider_count: number
    total_billing: number
    total_claims: number
    billing_share_pct: number
    top_providers: { npi: string; name: string; risk_score: number; total_paid: number }[]
  }[]
}

export interface BeneficiaryDensityResponse {
  states: BeneficiaryDensityState[]
  national_avg_billing_per_enrollee: number
  total_enrollment: number
  flagged_count: number
}

// ── Claim Pattern types ─────────────────────────────────────────────────────
export interface ClaimPatternSeverityCounts {
  CRITICAL: number
  HIGH: number
  MEDIUM: number
}

export interface ClaimPatternCategory {
  count: number
  total_paid: number
  severity_counts: ClaimPatternSeverityCounts
}

export interface ClaimPatternSummary {
  unbundling: ClaimPatternCategory
  duplicates: ClaimPatternCategory
  pos_violations: ClaimPatternCategory
  modifiers: ClaimPatternCategory
  impossible_days: ClaimPatternCategory
}

export interface ClaimPatternResult {
  patterns: Record<string, unknown>[]
  total: number
}

export interface ProviderClaimPatterns {
  npi: string
  unbundling: Record<string, unknown>[]
  duplicates: Record<string, unknown> | null
  pos_violations: Record<string, unknown> | null
  modifier_abuse: Record<string, unknown> | null
  impossible_days: Record<string, unknown> | null
}

// ── Supervised ML types ─────────────────────────────────────────────────────
export interface SupervisedModelStatus {
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

export interface SupervisedFeatureImportance {
  features: { feature: string; importance: number }[]
  error?: string
}

export interface SupervisedPrediction {
  npi: string
  fraud_probability: number
  label: number | null
  provider_name?: string
  state?: string
  total_paid?: number
  risk_score?: number
}

export interface SupervisedPredictionsResponse {
  predictions: SupervisedPrediction[]
  total: number
  limit: number
  offset: number
  error?: string
}
