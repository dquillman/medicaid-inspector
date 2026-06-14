import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

/**
 * At-a-glance "is it time to refresh?" strip for the Scan & Data page.
 * Each tile is dotted green/amber/red against the recommended cadence
 * (see the "How to refresh data" runbook).
 */

function ageDays(epochSec: number | null | undefined, nowSec: number): number | null {
  if (!epochSec) return null
  return Math.floor((nowSec - epochSec) / 86400)
}

function dotClass(days: number | null, amber: number, red: number): string {
  if (days == null) return 'bg-ink-ghost'
  if (days >= red) return 'bg-threat-critical'
  if (days >= amber) return 'bg-threat-medium'
  return 'bg-threat-clear'
}

function agonyLabel(days: number | null): string {
  if (days == null) return 'unknown'
  if (days === 0) return 'today'
  if (days === 1) return '1 day ago'
  if (days < 60) return `${days} days ago`
  return `${Math.floor(days / 30)} mo ago`
}

function Tile({ label, days, amber, red, sub }: { label: string; days: number | null; amber: number; red: number; sub: string }) {
  return (
    <div className="card py-2.5 px-3">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass(days, amber, red)}`} />
        <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.12em] truncate">{label}</p>
      </div>
      <p className="text-sm font-mono tabular-nums text-ink-secondary mt-1">{agonyLabel(days)}</p>
      <p className="text-[10px] text-ink-tertiary mt-0.5">{sub}</p>
    </div>
  )
}

export default function DataFreshnessStrip() {
  const { data, isError } = useQuery({
    queryKey: ['data-freshness'],
    queryFn: () => api.dataFreshness(),
    refetchInterval: 60_000,
    retry: 1,
  })
  if (isError || !data) return null

  const now = data.now
  const coreTs = data.core_dataset.mtime
    ?? (data.core_dataset.detected_date ? Date.parse(data.core_dataset.detected_date) / 1000 : null)
  const coreDays = ageDays(coreTs, now)
  const derivedTs = data.derived_generated_at ? Date.parse(data.derived_generated_at) / 1000 : null
  const derivedDays = ageDays(derivedTs, now)
  const scanDays = ageDays(data.last_scan_at, now)

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.14em] label-stamp">Data freshness</p>
        <span className="text-[10px] text-ink-tertiary">green = current · amber = due soon · red = overdue</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile
          label="Core Medicaid dataset"
          days={coreDays}
          amber={90}
          red={180}
          sub={data.core_dataset.is_local ? 'local · refresh quarterly' : 'remote · refresh quarterly'}
        />
        <Tile
          label="Derived data (NPPES/precompute)"
          days={derivedDays}
          amber={35}
          red={75}
          sub={`${data.deactivation_count.toLocaleString()} deactivated NPIs · refresh monthly`}
        />
        <Tile
          label="Last provider scan"
          days={scanDays}
          amber={45}
          red={120}
          sub="re-scan after a dataset update"
        />
        <div className="card py-2.5 px-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full shrink-0 bg-threat-clear" />
            <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.12em] truncate">OIG / SAM / Open Payments</p>
          </div>
          <p className="text-sm font-mono tabular-nums text-ink-secondary mt-1">auto</p>
          <p className="text-[10px] text-ink-tertiary mt-0.5">{data.oig_record_count.toLocaleString()} OIG records · always current</p>
        </div>
      </div>
    </div>
  )
}
