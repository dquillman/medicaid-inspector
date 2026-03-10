import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { OwnershipNetworkEntry, OwnershipNpi } from '../lib/types'

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v?.toFixed(2) ?? 0}`
}

function RiskBadge({ score }: { score: number }) {
  const cls = score >= 50
    ? 'bg-red-900 text-red-300'
    : score >= 25
      ? 'bg-orange-900 text-orange-300'
      : 'bg-gray-800 text-gray-400'
  return (
    <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${cls}`}>
      {score.toFixed(0)}
    </span>
  )
}

function ExpandedRow({ npis }: { npis: OwnershipNpi[] }) {
  return (
    <tr>
      <td colSpan={5} className="px-4 pb-4">
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-700">
                <th className="text-left px-4 py-2 font-medium">NPI</th>
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Type</th>
                <th className="text-left px-4 py-2 font-medium">Specialty</th>
                <th className="text-left px-4 py-2 font-medium">Risk</th>
                <th className="text-left px-4 py-2 font-medium">Billing</th>
                <th className="text-left px-4 py-2 font-medium">Flags</th>
                <th className="text-left px-4 py-2 font-medium">Location</th>
              </tr>
            </thead>
            <tbody>
              {npis.map(n => (
                <tr key={n.npi} className="border-b border-gray-800 last:border-0 hover:bg-gray-800/50">
                  <td className="px-4 py-2">
                    <Link to={`/providers/${n.npi}`} className="font-mono text-xs text-blue-400 hover:text-blue-300 underline">
                      {n.npi}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-gray-300 text-xs max-w-[180px] truncate" title={n.name}>
                    {n.name || '--'}
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">
                    {n.entity_type === 'NPI-2' ? 'Org' : 'Ind'}
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs max-w-[160px] truncate" title={n.specialty}>
                    {n.specialty || '--'}
                  </td>
                  <td className="px-4 py-2"><RiskBadge score={n.risk_score} /></td>
                  <td className="px-4 py-2 text-gray-400 text-xs font-mono">{fmt(n.total_paid)}</td>
                  <td className="px-4 py-2 text-xs">
                    {n.flag_count > 0
                      ? <span className="text-red-400">{n.flag_count}</span>
                      : <span className="text-gray-600">0</span>
                    }
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs truncate max-w-[140px]" title={`${n.address.city}, ${n.address.state}`}>
                    {n.address.city && n.address.state ? `${n.address.city}, ${n.address.state}` : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </td>
    </tr>
  )
}

export default function OwnershipNetworks() {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['ownership-networks'],
    queryFn: () => api.ownershipNetworks(),
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        Loading ownership networks...
      </div>
    )
  }

  if (error) {
    return <div className="card text-red-400">{String(error)}</div>
  }

  const networks = data?.networks ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Ownership Networks</h1>
          <p className="text-sm text-gray-500 mt-1">
            Authorized officials controlling 3 or more provider NPIs.
            {networks.length > 0 && (
              <span className="ml-2 text-gray-400">{networks.length} network{networks.length !== 1 ? 's' : ''} found</span>
            )}
          </p>
        </div>
      </div>

      {networks.length === 0 ? (
        <div className="card text-center text-gray-500 py-12">
          No ownership networks with 3+ entities found in scanned providers.
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-700 bg-gray-800/50">
                <th className="text-left px-4 py-3 font-medium">Authorized Official</th>
                <th className="text-left px-4 py-3 font-medium">Entities</th>
                <th className="text-left px-4 py-3 font-medium">Combined Billing</th>
                <th className="text-left px-4 py-3 font-medium">Avg Risk</th>
                <th className="text-left px-4 py-3 font-medium">Top Risk NPI</th>
              </tr>
            </thead>
            <tbody>
              {networks.map((net: OwnershipNetworkEntry, idx: number) => {
                const isExpanded = expandedIdx === idx
                return (
                  <>
                    <tr
                      key={`row-${idx}`}
                      className={`border-b border-gray-800 cursor-pointer transition-colors ${
                        isExpanded ? 'bg-gray-800/70' : 'hover:bg-gray-800/30'
                      }`}
                      onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs text-gray-500 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                            {'\u25B6'}
                          </span>
                          <span className="text-gray-200 font-medium">{net.official_name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="bg-blue-900/50 text-blue-300 text-xs font-bold px-2 py-0.5 rounded">
                          {net.npi_count}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-300 font-mono text-xs">{fmt(net.total_billing)}</td>
                      <td className="px-4 py-3"><RiskBadge score={net.avg_risk_score} /></td>
                      <td className="px-4 py-3">
                        <Link
                          to={`/providers/${net.top_risk_npi.npi}`}
                          className="text-blue-400 hover:text-blue-300 text-xs underline font-mono"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {net.top_risk_npi.npi}
                        </Link>
                        <span className="text-gray-500 text-xs ml-2">({net.top_risk_npi.risk_score.toFixed(0)})</span>
                      </td>
                    </tr>
                    {isExpanded && <ExpandedRow key={`expanded-${idx}`} npis={net.npis} />}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
