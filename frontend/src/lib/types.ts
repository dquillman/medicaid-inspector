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
