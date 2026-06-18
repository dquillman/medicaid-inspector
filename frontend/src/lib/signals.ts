/**
 * Per-provider "Top Fraud Odds" — rank a provider's fired fraud signals by how
 * much each contributes to the composite risk score, so the UI can show, at a
 * glance, the most likely fraud type(s) for that provider.
 *
 * The composite risk score = sum(score × weight) of the fired signals (capped at
 * 100). So a signal's CONTRIBUTION (score × weight) is exactly how much it drove
 * the provider's risk — the right thing to rank "fraud odds" by. We display each
 * signal's STRENGTH = score×100 (how hard that specific pattern fired, 0–100%).
 *
 * All inputs are already precomputed in the scan cache (`flags`), so this is
 * instant — no API call, no recompute.
 */

export interface Flag {
  signal: string
  score?: number
  weight?: number
  reason?: string
  flagged?: boolean
}

export interface FraudOdd {
  signal: string
  label: string
  reason: string
  contribution: number
  strength: number // 0–100
}

/** Human-readable names for the 18 detection signals (mirrors backend _SIGNAL_META). */
export const SIGNAL_LABELS: Record<string, string> = {
  billing_concentration: 'Billing Concentration',
  revenue_per_bene_outlier: 'Revenue / Beneficiary Outlier',
  claims_per_bene_anomaly: 'Claims / Beneficiary Anomaly',
  billing_ramp_rate: 'Billing Ramp Rate',
  bust_out_pattern: 'Bust-Out Pattern',
  ghost_billing: 'Ghost Billing',
  bene_concentration: 'Beneficiary Concentration',
  upcoding_pattern: 'Upcoding',
  address_cluster_risk: 'Address Cluster',
  oig_excluded: 'OIG Exclusion Match',
  specialty_mismatch: 'Specialty Mismatch',
  corporate_shell_risk: 'Corporate Shell',
  dead_npi_billing: 'Deactivated-NPI Billing',
  new_provider_explosion: 'New-Provider Explosion',
  geographic_impossibility: 'Geographic Impossibility',
  diagnosis_procedure_mismatch: 'Diagnosis–Procedure Mismatch',
  total_spend_outlier: 'Total Spend Outlier',
  billing_consistency: 'Billing Consistency Anomaly',
}

export function signalLabel(sig: string): string {
  return (
    SIGNAL_LABELS[sig] ||
    sig.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  )
}

/**
 * Rank a provider's fired signals into the top-N "fraud odds".
 * Ranked by contribution (score×weight); strength shown is score×100.
 */
export function topFraudOdds(flags: Flag[] | undefined | null, n = 3): FraudOdd[] {
  const scored = (flags || [])
    .filter((f) => f && f.signal && f.flagged !== false)
    .map((f) => ({
      signal: f.signal,
      label: signalLabel(f.signal),
      reason: f.reason || '',
      contribution: (Number(f.score) || 0) * (Number(f.weight) || 0),
      strength: Math.max(0, Math.min(100, Math.round((Number(f.score) || 0) * 100))),
    }))
    .filter((f) => f.contribution > 0)

  scored.sort((a, b) => b.contribution - a.contribution)
  return scored.slice(0, n)
}
