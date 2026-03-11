/**
 * Canonical dollar-formatting utility.
 *
 * Handles null/undefined gracefully and formats across four tiers:
 *   >= 1B  → $X.XXB
 *   >= 1M  → $X.XXM
 *   >= 1K  → $XXK
 *   <  1K  → $X.XX
 */
export function fmt(v: number | null | undefined): string {
  if (v == null) return '--'
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(2)}`
}

/**
 * Compact dollar-formatting variant (single-decimal M, whole-dollar fallback).
 *
 *   >= 1B  → $X.XB
 *   >= 1M  → $X.XM
 *   >= 1K  → $XXK
 *   <  1K  → $X
 */
export function fmtM(v: number): string {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}
