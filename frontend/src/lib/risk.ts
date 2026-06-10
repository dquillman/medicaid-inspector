/**
 * Canonical risk-score thresholds and colors — single source of truth.
 *
 * Every place a risk score is rendered (badges, table chips, row tints)
 * must derive its color from these helpers so a given score always reads
 * the same across screens. Thresholds follow RiskScoreBadge's original
 * scale: 70+ high, 50+ elevated, 40+ medium, below 40 low.
 */
export const RISK_HIGH = 70
export const RISK_ELEVATED = 50
export const RISK_MEDIUM = 40

export function riskLabel(score: number): string {
  if (score >= RISK_HIGH) return 'HIGH'
  if (score >= RISK_ELEVATED) return 'ELEVATED'
  if (score >= RISK_MEDIUM) return 'MED'
  return 'LOW'
}

/** Pill classes from index.css — used by RiskScoreBadge. */
export function riskBadgeClass(score: number): string {
  if (score >= RISK_HIGH) return 'badge-high'
  if (score >= RISK_MEDIUM) return 'badge-medium'
  return 'badge-low'
}

/** Compact bg/text combo for inline table chips and list rows. */
export function riskChipClass(score: number): string {
  if (score >= RISK_HIGH) return 'bg-red-900 text-red-300'
  if (score >= RISK_ELEVATED) return 'bg-orange-900 text-orange-300'
  if (score >= RISK_MEDIUM) return 'bg-yellow-900/50 text-yellow-300'
  return 'bg-gray-800 text-gray-400'
}
