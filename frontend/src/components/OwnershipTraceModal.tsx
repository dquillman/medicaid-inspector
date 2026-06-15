import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { get } from '../lib/api'
import type { OwnershipChain, AddressCluster } from '../lib/types'

interface OwnershipTraceModalProps {
  npi: string
  providerName: string
  onClose: () => void
}

function formatDollars(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

function riskBadgeClasses(score: number): string {
  if (score >= 75) return 'bg-red-900 text-red-300'
  if (score >= 50) return 'bg-orange-900 text-orange-300'
  return 'bg-yellow-900/50 text-yellow-300'
}

export default function OwnershipTraceModal({ npi, providerName, onClose }: OwnershipTraceModalProps) {
  const [chain, setChain] = useState<OwnershipChain | null>(null)
  const [cluster, setCluster] = useState<AddressCluster | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchData() {
      try {
        const [chainData, clusterData] = await Promise.all([
          get<OwnershipChain>(`/providers/${npi}/ownership-chain`),
          get<AddressCluster>(`/providers/${npi}/cluster`),
        ])
        if (!cancelled) {
          setChain(chainData)
          setCluster(clusterData)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load ownership data')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchData()
    return () => { cancelled = true }
  }, [npi])

  // Close on Escape
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose],
  )

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  return (
    <div
      className="fixed inset-0 bg-black/60 z-50 flex justify-center overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="max-w-5xl w-full mx-auto mt-12 mb-12 max-h-[85vh] overflow-y-auto bg-gray-900 border border-gray-700 rounded-xl shadow-2xl modal-pop elev-3">
        {/* Header */}
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-start justify-between z-10">
          <div>
            <h2 className="text-white font-bold text-lg">
              Ownership Network &mdash; NPI {npi}
            </h2>
            <p className="text-gray-400 text-sm mt-0.5">{providerName}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2 pt-1"
            aria-label="Close"
          >
            &#x2715;
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-16">
              <svg
                className="animate-spin h-8 w-8 text-blue-500"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              <span className="ml-3 text-gray-400 text-sm">Loading ownership data...</span>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="text-center py-12">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}

          {/* Content */}
          {!loading && !error && chain && cluster && (
            <>
              {/* Authorized Official */}
              <div className="bg-gray-800/60 rounded-lg px-4 py-3 text-sm">
                {chain.official ? (
                  <span className="text-gray-200">
                    <span className="font-semibold">Authorized Official:</span>{' '}
                    {chain.official.name} &mdash; {chain.official.title}
                  </span>
                ) : (
                  <span className="text-gray-500 italic">No authorized official on file</span>
                )}
              </div>

              {/* KPI Bar */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <KpiCard label="Total Entities" value={String(chain.total_entities)} />
                <KpiCard label="Combined Billing" value={formatDollars(chain.total_combined_billing)} />
                <KpiCard label="Shared Addresses" value={String(chain.shared_addresses.length)} />
                <KpiCard label="Cluster Providers" value={String(cluster.cluster.length)} />
              </div>

              {/* Controlled NPIs Table */}
              {chain.controlled_npis.length > 0 && (
                <section>
                  <h3 className="text-gray-300 font-semibold text-sm mb-3">
                    Controlled NPIs ({chain.controlled_npis.length})
                  </h3>
                  <div className="overflow-x-auto rounded-lg border border-gray-800">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-gray-800/80 text-gray-400 text-left">
                          <th className="px-3 py-2 font-medium">NPI</th>
                          <th className="px-3 py-2 font-medium">Name</th>
                          <th className="px-3 py-2 font-medium">Specialty</th>
                          <th className="px-3 py-2 font-medium text-center">Risk Score</th>
                          <th className="px-3 py-2 font-medium text-right">Total Paid</th>
                          <th className="px-3 py-2 font-medium text-center">Flags</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-800">
                        {chain.controlled_npis.map((p) => (
                          <tr key={p.npi} className="hover:bg-gray-800/40 transition-colors">
                            <td className="px-3 py-2">
                              <Link
                                to={`/providers/${p.npi}`}
                                className="text-blue-400 hover:text-blue-300 font-mono text-xs underline"
                              >
                                {p.npi}
                              </Link>
                            </td>
                            <td className="px-3 py-2 text-gray-200">{p.name}</td>
                            <td className="px-3 py-2 text-gray-400">{p.specialty}</td>
                            <td className="px-3 py-2 text-center">
                              <span
                                className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${riskBadgeClasses(p.risk_score)}`}
                              >
                                {p.risk_score}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right text-gray-200 font-mono">
                              {formatDollars(p.total_paid)}
                            </td>
                            <td className="px-3 py-2 text-center text-gray-300">{p.flag_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {/* Shared Address Cards */}
              {chain.shared_addresses.length > 0 && (
                <section>
                  <h3 className="text-gray-300 font-semibold text-sm mb-3">
                    Shared Addresses ({chain.shared_addresses.length})
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {chain.shared_addresses.map((sa, idx) => (
                      <div
                        key={idx}
                        className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-3"
                      >
                        <p className="text-gray-200 text-xs font-medium mb-2">{sa.address}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {sa.npis.map((sharedNpi) => (
                            <Link
                              key={sharedNpi}
                              to={`/providers/${sharedNpi}`}
                              className="text-blue-400 hover:text-blue-300 font-mono text-xs underline"
                            >
                              {sharedNpi}
                            </Link>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Address Cluster */}
              {cluster.cluster.length > 0 && (
                <section>
                  <h3 className="text-gray-300 font-semibold text-sm mb-3">
                    Address Cluster &mdash; Same Location Providers ({cluster.cluster.length})
                  </h3>
                  <p className="text-gray-500 text-xs mb-3">
                    {cluster.address.line1}, {cluster.address.city}, {cluster.address.state}{' '}
                    {cluster.address.zip}
                  </p>
                  <div className="overflow-x-auto rounded-lg border border-gray-800">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-gray-800/80 text-gray-400 text-left">
                          <th className="px-3 py-2 font-medium">NPI</th>
                          <th className="px-3 py-2 font-medium">Name</th>
                          <th className="px-3 py-2 font-medium">Specialty</th>
                          <th className="px-3 py-2 font-medium text-center">Risk Score</th>
                          <th className="px-3 py-2 font-medium text-right">Total Paid</th>
                          <th className="px-3 py-2 font-medium text-center">Flags</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-800">
                        {cluster.cluster.map((cp) => (
                          <tr key={cp.npi} className="hover:bg-gray-800/40 transition-colors">
                            <td className="px-3 py-2">
                              <Link
                                to={`/providers/${cp.npi}`}
                                className="text-blue-400 hover:text-blue-300 font-mono text-xs underline"
                              >
                                {cp.npi}
                              </Link>
                            </td>
                            <td className="px-3 py-2 text-gray-200">{cp.provider_name}</td>
                            <td className="px-3 py-2 text-gray-400">{cp.specialty}</td>
                            <td className="px-3 py-2 text-center">
                              <span
                                className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${riskBadgeClasses(cp.risk_score)}`}
                              >
                                {cp.risk_score}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right text-gray-200 font-mono">
                              {formatDollars(cp.total_paid)}
                            </td>
                            <td className="px-3 py-2 text-center text-gray-300">{cp.flag_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {/* Empty state */}
              {chain.controlled_npis.length === 0 &&
                chain.shared_addresses.length === 0 &&
                cluster.cluster.length === 0 && (
                  <div className="text-center py-12">
                    <p className="text-gray-500 text-sm">
                      No ownership network data found for this provider.
                    </p>
                  </div>
                )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-3 text-center">
      <div className="text-white font-bold text-lg">{value}</div>
      <div className="text-gray-400 text-xs mt-0.5">{label}</div>
    </div>
  )
}
