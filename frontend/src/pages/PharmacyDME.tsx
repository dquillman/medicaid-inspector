import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { PharmacyProviderFlag, DMEProviderFlag } from '../lib/types'

type SortKey = string
type SortDir = 'asc' | 'desc'

function fmt$(n: number) {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function fmtPct(n: number) {
  return `${n.toFixed(1)}%`
}

function SeverityBadge({ count }: { count: number }) {
  if (count === 0) return <span className="text-gray-500 text-xs">--</span>
  const cls = count >= 3
    ? 'bg-red-900/50 text-red-300 border-red-700'
    : count >= 2
      ? 'bg-orange-900/50 text-orange-300 border-orange-700'
      : 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium border ${cls}`}>
      {count} flag{count !== 1 ? 's' : ''}
    </span>
  )
}

// ── Pharmacy Tab ──────────────────────────────────────────────────────────────

function PharmacyTab() {
  const navigate = useNavigate()
  const [sortKey, setSortKey] = useState<SortKey>('pharmacy_risk')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const { data, isLoading, error } = useQuery({
    queryKey: ['pharmacy-high-risk'],
    queryFn: () => api.pharmacyHighRisk(100),
    staleTime: 30_000,
  })

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  if (isLoading) return <div className="text-gray-400 animate-pulse text-center py-12">Loading pharmacy fraud data...</div>
  if (error) return <div className="card p-6 text-center text-red-400">Failed to load pharmacy data: {String(error)}</div>
  if (!data?.available) return <div className="card p-6 text-center text-gray-400">{data?.note || 'Pharmacy analysis not available. Run a scan first.'}</div>

  const kpis = data.kpis
  const sorted = [...(data.providers || [])].sort((a: any, b: any) => {
    const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  const SortHeader = ({ k, label, className = '' }: { k: string; label: string; className?: string }) => (
    <th className={`px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase cursor-pointer hover:text-white select-none ${className}`}
        onClick={() => toggleSort(k)}>
      {label} {sortKey === k ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
    </th>
  )

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      {kpis && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <KpiCard label="Drug Providers" value={kpis.total_drug_providers.toLocaleString()} />
          <KpiCard label="Total Drug Billing" value={fmt$(kpis.total_drug_billing)} />
          <KpiCard label="Avg Drug %" value={fmtPct(kpis.avg_drug_pct)} />
          <KpiCard label="Flagged" value={kpis.flagged_count.toLocaleString()} accent="red" />
          <KpiCard label="High-Cost Drug" value={kpis.high_cost_count.toLocaleString()} accent="orange" />
          <KpiCard label="Controlled Sub." value={kpis.controlled_count.toLocaleString()} accent="yellow" />
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/60 border-b border-gray-700">
              <tr>
                <SortHeader k="provider_name" label="Provider" />
                <SortHeader k="state" label="State" />
                <SortHeader k="drug_paid" label="Drug Billing" />
                <SortHeader k="drug_pct" label="Drug %" />
                <SortHeader k="high_cost_pct" label="High-Cost %" />
                <SortHeader k="controlled_pct" label="Controlled %" />
                <SortHeader k="unclassified_pct" label="Unclassified %" />
                <SortHeader k="flag_count" label="Flags" />
                <SortHeader k="pharmacy_risk" label="Pharma Risk" />
                <SortHeader k="risk_score" label="Overall Risk" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {sorted.map((p: PharmacyProviderFlag) => (
                <tr key={p.npi} className="hover:bg-gray-800/40 cursor-pointer transition-colors"
                    onClick={() => navigate(`/providers/${p.npi}`)}>
                  <td className="px-3 py-2">
                    <div className="font-medium text-white">{p.provider_name || p.npi}</div>
                    <div className="text-xs text-gray-500">{p.npi}</div>
                  </td>
                  <td className="px-3 py-2 text-gray-300">{p.state}</td>
                  <td className="px-3 py-2 text-gray-300">{fmt$(p.drug_paid)}</td>
                  <td className="px-3 py-2 text-gray-300">{fmtPct(p.drug_pct)}</td>
                  <td className="px-3 py-2">
                    <span className={p.high_cost_pct > 30 ? 'text-red-400 font-medium' : 'text-gray-400'}>
                      {fmtPct(p.high_cost_pct)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={p.controlled_pct > 15 ? 'text-orange-400 font-medium' : 'text-gray-400'}>
                      {fmtPct(p.controlled_pct)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={p.unclassified_pct > 10 ? 'text-yellow-400 font-medium' : 'text-gray-400'}>
                      {fmtPct(p.unclassified_pct)}
                    </span>
                  </td>
                  <td className="px-3 py-2"><SeverityBadge count={p.flag_count} /></td>
                  <td className="px-3 py-2">
                    <RiskBar value={p.pharmacy_risk} />
                  </td>
                  <td className="px-3 py-2">
                    <RiskBar value={p.risk_score} />
                  </td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr><td colSpan={10} className="px-3 py-8 text-center text-gray-500">No pharmacy fraud indicators detected</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── DME Tab ───────────────────────────────────────────────────────────────────

function DMETab() {
  const navigate = useNavigate()
  const [sortKey, setSortKey] = useState<SortKey>('dme_risk')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const { data, isLoading, error } = useQuery({
    queryKey: ['dme-high-risk'],
    queryFn: () => api.dmeHighRisk(100),
    staleTime: 30_000,
  })

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  if (isLoading) return <div className="text-gray-400 animate-pulse text-center py-12">Loading DME fraud data...</div>
  if (error) return <div className="card p-6 text-center text-red-400">Failed to load DME data: {String(error)}</div>
  if (!data?.available) return <div className="card p-6 text-center text-gray-400">{data?.note || 'DME analysis not available. Run a scan first.'}</div>

  const kpis = data.kpis
  const sorted = [...(data.providers || [])].sort((a: any, b: any) => {
    const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  const SortHeader = ({ k, label, className = '' }: { k: string; label: string; className?: string }) => (
    <th className={`px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase cursor-pointer hover:text-white select-none ${className}`}
        onClick={() => toggleSort(k)}>
      {label} {sortKey === k ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
    </th>
  )

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      {kpis && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <KpiCard label="DME Providers" value={kpis.total_dme_providers.toLocaleString()} />
          <KpiCard label="Total DME Billing" value={fmt$(kpis.total_dme_billing)} />
          <KpiCard label="Avg DME %" value={fmtPct(kpis.avg_dme_pct)} />
          <KpiCard label="Flagged" value={kpis.flagged_count.toLocaleString()} accent="red" />
          <KpiCard label="High-Cost DME" value={kpis.high_cost_count.toLocaleString()} accent="orange" />
          <KpiCard label="No E&M Visits" value={kpis.no_em_count.toLocaleString()} accent="yellow" />
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/60 border-b border-gray-700">
              <tr>
                <SortHeader k="provider_name" label="Provider" />
                <SortHeader k="state" label="State" />
                <SortHeader k="dme_paid" label="DME Billing" />
                <SortHeader k="dme_pct" label="DME %" />
                <SortHeader k="high_cost_pct" label="High-Cost %" />
                <SortHeader k="z_score" label="Volume Z-Score" />
                <SortHeader k="em_claims" label="E&M Claims" />
                <SortHeader k="rental_pct" label="Rental %" />
                <SortHeader k="flag_count" label="Flags" />
                <SortHeader k="dme_risk" label="DME Risk" />
                <SortHeader k="risk_score" label="Overall Risk" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {sorted.map((p: DMEProviderFlag) => (
                <tr key={p.npi} className="hover:bg-gray-800/40 cursor-pointer transition-colors"
                    onClick={() => navigate(`/providers/${p.npi}`)}>
                  <td className="px-3 py-2">
                    <div className="font-medium text-white">{p.provider_name || p.npi}</div>
                    <div className="text-xs text-gray-500">{p.npi}</div>
                  </td>
                  <td className="px-3 py-2 text-gray-300">{p.state}</td>
                  <td className="px-3 py-2 text-gray-300">{fmt$(p.dme_paid)}</td>
                  <td className="px-3 py-2 text-gray-300">{fmtPct(p.dme_pct)}</td>
                  <td className="px-3 py-2">
                    <span className={p.high_cost_pct > 25 ? 'text-red-400 font-medium' : 'text-gray-400'}>
                      {fmtPct(p.high_cost_pct)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={p.z_score > 2 ? 'text-orange-400 font-medium' : 'text-gray-400'}>
                      {p.z_score.toFixed(1)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={p.dme_claims > 10 && p.em_claims === 0 ? 'text-red-400 font-medium' : 'text-gray-400'}>
                      {p.em_claims.toLocaleString()}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={p.rental_pct > 30 ? 'text-yellow-400 font-medium' : 'text-gray-400'}>
                      {fmtPct(p.rental_pct)}
                    </span>
                  </td>
                  <td className="px-3 py-2"><SeverityBadge count={p.flag_count} /></td>
                  <td className="px-3 py-2">
                    <RiskBar value={p.dme_risk} />
                  </td>
                  <td className="px-3 py-2">
                    <RiskBar value={p.risk_score} />
                  </td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr><td colSpan={11} className="px-3 py-8 text-center text-gray-500">No DME fraud indicators detected</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── Shared components ─────────────────────────────────────────────────────────

function KpiCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  const accentCls = accent === 'red'
    ? 'text-red-400'
    : accent === 'orange'
      ? 'text-orange-400'
      : accent === 'yellow'
        ? 'text-yellow-400'
        : 'text-white'
  return (
    <div className="card p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-xl font-bold ${accentCls}`}>{value}</div>
    </div>
  )
}

function RiskBar({ value }: { value: number }) {
  const pct = Math.min(value, 100)
  const color = pct >= 70 ? 'bg-red-500' : pct >= 40 ? 'bg-orange-500' : pct >= 20 ? 'bg-yellow-500' : 'bg-green-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-8">{pct.toFixed(0)}</span>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const TABS = ['Pharmacy Fraud', 'DME Fraud'] as const

export default function PharmacyDME() {
  const [tab, setTab] = useState<string>('Pharmacy Fraud')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Pharmacy & DME Fraud Detection</h1>
          <p className="text-gray-400 text-sm mt-1">
            Identify providers with suspicious pharmacy drug billing or DME equipment patterns
          </p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-700 pb-0">
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium rounded-t transition-colors ${
              tab === t
                ? 'bg-gray-800 text-white border-b-2 border-blue-500'
                : 'text-gray-400 hover:text-white hover:bg-gray-800/50'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Pharmacy Fraud' ? <PharmacyTab /> : <DMETab />}
    </div>
  )
}
