import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { fmt } from '../lib/format'

function num(v: number | null | undefined) {
  if (v == null) return '--'
  return v.toLocaleString()
}

type Tab = 'shopping' | 'utilization' | 'geographic' | 'excessive'

const TABS: { key: Tab; label: string; desc: string }[] = [
  { key: 'shopping', label: 'Doctor Shopping', desc: 'Providers whose patients likely visit many other providers for the same services' },
  { key: 'utilization', label: 'High Utilization', desc: 'Providers with claims/revenue per beneficiary far exceeding peers' },
  { key: 'geographic', label: 'Geographic Anomalies', desc: 'Providers billing from multiple states — possible geographic impossibility' },
  { key: 'excessive', label: 'Excessive Services', desc: 'Providers with service counts per beneficiary exceeding 90th percentile' },
]

function KpiCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">{label}</div>
      <div className="text-2xl font-bold text-white">{typeof value === 'number' ? value.toLocaleString() : value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

function SortHeader({ label, field, sortBy, sortDir, onSort }: {
  label: string; field: string; sortBy: string; sortDir: 'asc' | 'desc'
  onSort: (f: string) => void
}) {
  return (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase tracking-wider cursor-pointer hover:text-white select-none"
      onClick={() => onSort(field)}
    >
      {label}
      {sortBy === field && (sortDir === 'asc' ? ' \u25B2' : ' \u25BC')}
    </th>
  )
}

function DoctorShoppingTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['bene-fraud-shopping'],
    queryFn: () => api.beneficiaryFraudDoctorShopping(),
  })
  const [sortBy, setSortBy] = useState('shopping_score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const onSort = (f: string) => {
    if (sortBy === f) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(f); setSortDir('desc') }
  }

  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading doctor shopping data...</div>
  if (error) return <div className="text-red-400 py-8 text-center">Error: {(error as Error).message}</div>

  const rows = [...(data?.flagged || [])].sort((a: any, b: any) => {
    const av = a[sortBy] ?? 0, bv = b[sortBy] ?? 0
    return sortDir === 'asc' ? av - bv : bv - av
  })

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700">
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">NPI</th>
            <SortHeader label="Shopping Score" field="shopping_score" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Shared Codes" field="shared_code_count" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Max Competing" field="max_competing_providers" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Claims/Bene" field="claims_per_bene" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Total Paid" field="total_paid" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Benes" field="total_benes" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.npi} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="px-3 py-2">
                <Link to={`/providers/${r.npi}`} className="text-blue-400 hover:text-blue-300 font-mono text-xs">{r.npi}</Link>
              </td>
              <td className="px-3 py-2 text-orange-400 font-semibold">{(r.shopping_score ?? 0).toFixed(1)}</td>
              <td className="px-3 py-2 text-gray-300">{num(r.shared_code_count)}</td>
              <td className="px-3 py-2 text-gray-300">{num(r.max_competing_providers)}</td>
              <td className="px-3 py-2 text-gray-300">{(r.claims_per_bene ?? 0).toFixed(1)}</td>
              <td className="px-3 py-2 text-gray-300">{fmt(r.total_paid)}</td>
              <td className="px-3 py-2 text-gray-300">{num(r.total_benes)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-500">No doctor shopping patterns detected</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function HighUtilizationTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['bene-fraud-utilization'],
    queryFn: () => api.beneficiaryFraudHighUtilization(),
  })
  const [sortBy, setSortBy] = useState('cpb_z_score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const onSort = (f: string) => {
    if (sortBy === f) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(f); setSortDir('desc') }
  }

  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading high utilization data...</div>
  if (error) return <div className="text-red-400 py-8 text-center">Error: {(error as Error).message}</div>

  const rows = [...(data?.flagged || [])].sort((a: any, b: any) => {
    const av = a[sortBy] ?? 0, bv = b[sortBy] ?? 0
    return sortDir === 'asc' ? av - bv : bv - av
  })

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700">
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">NPI</th>
            <SortHeader label="Claims/Bene" field="claims_per_bene" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="CPB Z-Score" field="cpb_z_score" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Rev/Bene" field="rev_per_bene" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="RPB Z-Score" field="rpb_z_score" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Total Paid" field="total_paid" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Benes" field="total_benes" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">Peer P90</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.npi} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="px-3 py-2">
                <Link to={`/providers/${r.npi}`} className="text-blue-400 hover:text-blue-300 font-mono text-xs">{r.npi}</Link>
              </td>
              <td className="px-3 py-2 text-gray-300">{(r.claims_per_bene ?? 0).toFixed(1)}</td>
              <td className="px-3 py-2">
                <span className={r.cpb_z_score > 3 ? 'text-red-400 font-bold' : r.cpb_z_score > 2 ? 'text-orange-400' : 'text-yellow-400'}>
                  {(r.cpb_z_score ?? 0).toFixed(1)}
                </span>
              </td>
              <td className="px-3 py-2 text-gray-300">{fmt(r.rev_per_bene)}</td>
              <td className="px-3 py-2">
                <span className={r.rpb_z_score > 3 ? 'text-red-400 font-bold' : r.rpb_z_score > 2 ? 'text-orange-400' : 'text-yellow-400'}>
                  {(r.rpb_z_score ?? 0).toFixed(1)}
                </span>
              </td>
              <td className="px-3 py-2 text-gray-300">{fmt(r.total_paid)}</td>
              <td className="px-3 py-2 text-gray-300">{num(r.total_benes)}</td>
              <td className="px-3 py-2 text-gray-500 text-xs">CPB: {(r.peer_p90_cpb ?? 0).toFixed(1)} | RPB: {fmt(r.peer_p90_rpb)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-500">No high utilization patterns detected</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function GeographicTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['bene-fraud-geographic'],
    queryFn: () => api.beneficiaryFraudGeographic(),
  })
  const [sortBy, setSortBy] = useState('geo_risk_score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const onSort = (f: string) => {
    if (sortBy === f) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(f); setSortDir('desc') }
  }

  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading geographic anomaly data...</div>
  if (error) return <div className="text-red-400 py-8 text-center">Error: {(error as Error).message}</div>

  if (data?.note && (data?.flagged?.length ?? 0) === 0) {
    return <div className="text-gray-500 py-8 text-center">{data.note}</div>
  }

  const rows = [...(data?.flagged || [])].sort((a: any, b: any) => {
    const av = a[sortBy] ?? 0, bv = b[sortBy] ?? 0
    return sortDir === 'asc' ? av - bv : bv - av
  })

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700">
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">NPI</th>
            <SortHeader label="Geo Risk" field="geo_risk_score" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="States" field="state_count" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">State List</th>
            <SortHeader label="Servicing NPIs" field="servicing_npi_count" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Total Paid" field="total_paid" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Benes" field="total_benes" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.npi} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="px-3 py-2">
                <Link to={`/providers/${r.npi}`} className="text-blue-400 hover:text-blue-300 font-mono text-xs">{r.npi}</Link>
              </td>
              <td className="px-3 py-2 text-red-400 font-semibold">{num(r.geo_risk_score)}</td>
              <td className="px-3 py-2 text-gray-300">{r.state_count}</td>
              <td className="px-3 py-2">
                <div className="flex gap-1 flex-wrap">
                  {(Array.isArray(r.states) ? r.states : []).map((s: string) => (
                    <span key={s} className="px-1.5 py-0.5 bg-gray-700 rounded text-xs text-gray-300">{s}</span>
                  ))}
                </div>
              </td>
              <td className="px-3 py-2 text-gray-300">{num(r.servicing_npi_count)}</td>
              <td className="px-3 py-2 text-gray-300">{fmt(r.total_paid)}</td>
              <td className="px-3 py-2 text-gray-300">{num(r.total_benes)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-500">No geographic anomalies detected</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function ExcessiveServicesTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['bene-fraud-excessive'],
    queryFn: () => api.beneficiaryFraudExcessive(),
  })
  const [sortBy, setSortBy] = useState('svc_per_bene')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const onSort = (f: string) => {
    if (sortBy === f) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(f); setSortDir('desc') }
  }

  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading excessive services data...</div>
  if (error) return <div className="text-red-400 py-8 text-center">Error: {(error as Error).message}</div>

  const rows = [...(data?.flagged || [])].sort((a: any, b: any) => {
    const av = a[sortBy] ?? 0, bv = b[sortBy] ?? 0
    return sortDir === 'asc' ? av - bv : bv - av
  })

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700">
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">NPI</th>
            <SortHeader label="Svc/Bene" field="svc_per_bene" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Z-Score" field="z_score" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="x Median" field="multiple_of_median" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Total Services" field="total_services" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Total Paid" field="total_paid" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <SortHeader label="Benes" field="total_benes" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-400">Peer Median</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.npi} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="px-3 py-2">
                <Link to={`/providers/${r.npi}`} className="text-blue-400 hover:text-blue-300 font-mono text-xs">{r.npi}</Link>
              </td>
              <td className="px-3 py-2 text-orange-400 font-semibold">{(r.svc_per_bene ?? 0).toFixed(1)}</td>
              <td className="px-3 py-2">
                <span className={r.z_score > 3 ? 'text-red-400 font-bold' : r.z_score > 2 ? 'text-orange-400' : 'text-yellow-400'}>
                  {(r.z_score ?? 0).toFixed(1)}
                </span>
              </td>
              <td className="px-3 py-2 text-gray-300">{(r.multiple_of_median ?? 0).toFixed(1)}x</td>
              <td className="px-3 py-2 text-gray-300">{num(r.total_services)}</td>
              <td className="px-3 py-2 text-gray-300">{fmt(r.total_paid)}</td>
              <td className="px-3 py-2 text-gray-300">{num(r.total_benes)}</td>
              <td className="px-3 py-2 text-gray-500 text-xs">{(r.peer_median ?? 0).toFixed(1)} | P90: {(r.peer_p90 ?? 0).toFixed(1)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-500">No excessive service patterns detected</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function BeneficiaryFraud() {
  const [tab, setTab] = useState<Tab>('shopping')

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['bene-fraud-summary'],
    queryFn: () => api.beneficiaryFraudSummary(),
  })

  const counts: Record<string, number> = summary?.flagged_counts || {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Beneficiary Fraud Detection</h1>
        <p className="text-gray-400 text-sm mt-1">
          Identify provider patterns that indicate beneficiary-level fraud: doctor shopping, excessive utilization, and geographic anomalies
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard
          label="Providers Analyzed"
          value={summaryLoading ? '...' : num(summary?.total_providers_analyzed)}
        />
        <KpiCard
          label="Doctor Shopping"
          value={summaryLoading ? '...' : counts.doctor_shopping ?? 0}
          sub="provider-level flags"
        />
        <KpiCard
          label="High Utilization"
          value={summaryLoading ? '...' : counts.high_utilization ?? 0}
          sub="above P90 thresholds"
        />
        <KpiCard
          label="Geographic Anomalies"
          value={summaryLoading ? '...' : counts.geographic_anomalies ?? 0}
          sub="multi-state billing"
        />
        <KpiCard
          label="Excessive Services"
          value={summaryLoading ? '...' : counts.excessive_services ?? 0}
          sub="svc/bene outliers"
        />
        <KpiCard
          label="Total Billing"
          value={summaryLoading ? '...' : fmt(summary?.total_paid)}
        />
      </div>

      {/* Data note */}
      {summary?.note && (
        <div className="bg-blue-900/20 border border-blue-800/40 rounded-lg px-4 py-2 text-xs text-blue-300">
          {summary.note}
        </div>
      )}

      {/* Tabs */}
      <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
        <div className="flex border-b border-gray-700">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-3 text-sm font-medium transition-colors ${
                tab === t.key
                  ? 'text-blue-400 border-b-2 border-blue-400 bg-gray-800/50'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800/30'
              }`}
            >
              {t.label}
              {counts[t.key === 'shopping' ? 'doctor_shopping' : t.key === 'utilization' ? 'high_utilization' : t.key === 'geographic' ? 'geographic_anomalies' : 'excessive_services'] > 0 && (
                <span className="ml-1.5 px-1.5 py-0.5 bg-red-900/50 text-red-400 text-xs rounded-full">
                  {counts[t.key === 'shopping' ? 'doctor_shopping' : t.key === 'utilization' ? 'high_utilization' : t.key === 'geographic' ? 'geographic_anomalies' : 'excessive_services']}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab description */}
        <div className="px-4 py-2 bg-gray-800/30 border-b border-gray-700">
          <p className="text-xs text-gray-500">{TABS.find(t => t.key === tab)?.desc}</p>
        </div>

        {/* Tab content */}
        <div className="p-0">
          {tab === 'shopping' && <DoctorShoppingTable />}
          {tab === 'utilization' && <HighUtilizationTable />}
          {tab === 'geographic' && <GeographicTable />}
          {tab === 'excessive' && <ExcessiveServicesTable />}
        </div>
      </div>
    </div>
  )
}
