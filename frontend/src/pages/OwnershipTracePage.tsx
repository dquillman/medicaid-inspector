import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import type { OwnershipChain, AddressCluster } from '../lib/types'
import ProviderFlags from '../components/ProviderFlags'

function riskBadgeClasses(score: number): string {
  if (score >= 75) return 'bg-red-900 text-red-300'
  if (score >= 50) return 'bg-orange-900 text-orange-300'
  return 'bg-yellow-900/50 text-yellow-300'
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4 text-center">
      <div className="text-white font-bold text-xl">{value}</div>
      <div className="text-gray-400 text-xs mt-1">{label}</div>
    </div>
  )
}

export default function OwnershipTracePage() {
  const { npi } = useParams<{ npi: string }>()

  const { data: provider } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })

  const {
    data: chain,
    isLoading: chainLoading,
    error: chainError,
  } = useQuery<OwnershipChain>({
    queryKey: ['ownership-chain', npi],
    queryFn: () => api.ownershipChain(npi!),
    enabled: !!npi,
  })

  const {
    data: cluster,
    isLoading: clusterLoading,
    error: clusterError,
  } = useQuery<AddressCluster>({
    queryKey: ['address-cluster', npi],
    queryFn: () => api.addressCluster(npi!),
    enabled: !!npi,
  })

  const loading = chainLoading || clusterLoading
  const error = chainError || clusterError
  const providerName = provider?.nppes?.name ?? provider?.provider_name ?? npi

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/providers" className="hover:text-gray-300">
          Providers
        </Link>
        <span>/</span>
        <Link to={`/providers/${npi}`} className="hover:text-gray-300 font-mono">
          {npi}
        </Link>
        <span>/</span>
        <span className="text-gray-300">Ownership Network</span>
      </div>

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-white font-bold text-xl">Ownership Network Trace</h1>
          <p className="text-gray-400 text-sm mt-0.5">{providerName}</p>
        </div>
        <Link
          to={`/providers/${npi}`}
          className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          &larr; Back to Provider
        </Link>
      </div>

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
          <p className="text-red-400 text-sm">
            {error instanceof Error ? error.message : 'Failed to load ownership data'}
          </p>
        </div>
      )}

      {/* Content */}
      {!loading && !error && chain && cluster && (
        <>
          {/* Authorized Official banner */}
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

          {/* KPI Grid */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {chain.cluster_risk_score !== undefined && (
              <KpiCard
                label="Cluster Risk"
                value={`${chain.cluster_risk_score}${chain.cluster_risk_band ? ` · ${chain.cluster_risk_band}` : ''}`}
              />
            )}
            <KpiCard label="Total Entities" value={String(chain.total_entities)} />
            <KpiCard label="Combined Billing" value={fmt(chain.total_combined_billing)} />
            <KpiCard label="Shared Addresses" value={String(chain.shared_addresses.length)} />
            <KpiCard label="Cluster Size" value={String(cluster.cluster.length)} />
          </div>

          {/* Controlled NPIs Table */}
          {chain.controlled_npis.length > 0 && (
            <section className="card">
              <h2 className="text-gray-300 font-semibold text-sm mb-3">
                Controlled NPIs ({chain.controlled_npis.length})
              </h2>
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
                        <td className="px-3 py-2 text-gray-200">
                          {p.name}
                          <ProviderFlags npi={p.npi} className="ml-1.5" />
                        </td>
                        <td className="px-3 py-2 text-gray-400">{p.specialty}</td>
                        <td className="px-3 py-2 text-center">
                          <span
                            className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${riskBadgeClasses(p.risk_score)}`}
                          >
                            {p.risk_score}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right text-gray-200 font-mono">
                          {fmt(p.total_paid)}
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
              <h2 className="text-gray-300 font-semibold text-sm mb-3">
                Shared Addresses ({chain.shared_addresses.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {chain.shared_addresses.map((sa, idx) => (
                  <div
                    key={idx}
                    className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4"
                  >
                    <p className="text-gray-200 text-sm font-medium mb-2">{sa.address}</p>
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
            <section className="card">
              <h2 className="text-gray-300 font-semibold text-sm mb-3">
                Address Cluster &mdash; Same Location Providers ({cluster.cluster.length})
              </h2>
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
                        <td className="px-3 py-2 text-gray-200">
                          {cp.provider_name}
                          <ProviderFlags npi={cp.npi} className="ml-1.5" />
                        </td>
                        <td className="px-3 py-2 text-gray-400">{cp.specialty}</td>
                        <td className="px-3 py-2 text-center">
                          <span
                            className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${riskBadgeClasses(cp.risk_score)}`}
                          >
                            {cp.risk_score}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right text-gray-200 font-mono">
                          {fmt(cp.total_paid)}
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
  )
}
