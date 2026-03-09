import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import RiskScoreBadge from '../components/RiskScoreBadge'
import SpendingTimeline from '../components/SpendingTimeline'
import HcpcsBreakdown from '../components/HcpcsBreakdown'
import FraudFlagsTable from '../components/FraudFlagsTable'
import RiskScoreModal from '../components/RiskScoreModal'
import type { ClusterProvider, OpenPaymentsData, SamExclusion } from '../lib/types'

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v?.toFixed(2) ?? 0}`
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return '—'
  const color = v >= 90 ? 'text-red-400' : v >= 75 ? 'text-orange-400' : v >= 50 ? 'text-yellow-400' : 'text-green-400'
  return <span className={`font-bold ${color}`}>{v.toFixed(0)}th percentile</span>
}

function PeerRow({ label, value, stats, pct, money = true }: {
  label: string
  value: number
  stats: { mean: number; median: number; p75: number; p90: number } | null
  pct: number | null | undefined
  money?: boolean
}) {
  if (!stats) return null
  const fv = (v: number) => money ? fmt(v) : v.toFixed(1)
  return (
    <tr className="border-b border-gray-800 text-sm">
      <td className="py-2 pr-4 text-gray-400">{label}</td>
      <td className="py-2 pr-4 font-mono text-white">{fv(value)}</td>
      <td className="py-2 pr-4 text-gray-500">{fv(stats.median)} median</td>
      <td className="py-2 pr-4 text-gray-500">{fv(stats.p90)} p90</td>
      <td className="py-2">{fmtPct(pct)}</td>
    </tr>
  )
}

export default function ProviderDetail() {
  const { npi } = useParams<{ npi: string }>()

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })

  const { data: timelineData } = useQuery({
    queryKey: ['timeline', npi],
    queryFn: () => api.providerTimeline(npi!),
    enabled: !!npi,
  })

  const { data: hcpcsData } = useQuery({
    queryKey: ['hcpcs', npi],
    queryFn: () => api.providerHcpcs(npi!),
    enabled: !!npi,
  })

  const { data: oigData } = useQuery({
    queryKey: ['oig', npi],
    queryFn: () => api.oigStatus(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: clusterData } = useQuery({
    queryKey: ['cluster', npi],
    queryFn: () => api.addressCluster(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: peersData } = useQuery({
    queryKey: ['peers', npi],
    queryFn: () => api.providerPeers(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: openPaymentsData } = useQuery<OpenPaymentsData>({
    queryKey: ['open-payments', npi],
    queryFn: () => api.openPayments(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: samData } = useQuery<SamExclusion>({
    queryKey: ['sam-exclusion', npi],
    queryFn: () => api.samExclusion(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        Loading provider data…
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="card text-red-400">
        {String(error ?? 'Provider not found')}
      </div>
    )
  }

  const nppes = detail.nppes ?? {}
  const addr  = nppes.address ?? {}
  const tax   = nppes.taxonomy ?? {}

  const cluster      = clusterData?.cluster ?? []
  const peers        = peersData
  const oigExcluded  = oigData?.excluded ?? false

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Link to="/providers" className="hover:text-gray-300">Providers</Link>
          <span>/</span>
          <span className="font-mono-data">{npi}</span>
        </div>
        <button
          onClick={() => window.print()}
          className="no-print px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-300 text-xs rounded transition-colors flex items-center gap-1.5"
          title="Print this page"
        >
          <span>🖨</span> Print
        </button>
      </div>

      {/* OIG Exclusion Banner — full-width, impossible to miss */}
      {oigExcluded && oigData?.record && (
        <div className="bg-red-950 border-2 border-red-600 rounded-xl px-6 py-5 flex items-start gap-4 shadow-lg shadow-red-950/50" style={{ animation: 'threat-pulse-bg 2.5s ease-in-out infinite' }}>
          <span className="text-red-500 text-3xl mt-0.5 font-black">{'\u26D4'}</span>
          <div className="flex-1">
            <p className="text-red-300 font-black text-base uppercase tracking-wider">OIG EXCLUSION LIST -- PROVIDER EXCLUDED FROM FEDERAL HEALTHCARE PROGRAMS</p>
            <p className="text-red-400 text-sm mt-2 font-mono">
              {oigData.record.excl_type && <span className="mr-4 inline-block">TYPE: {oigData.record.excl_type}</span>}
              {oigData.record.excl_date && <span className="mr-4 inline-block">DATE: {oigData.record.excl_date}</span>}
              {oigData.record.specialty && <span className="inline-block">SPECIALTY: {oigData.record.specialty}</span>}
            </p>
          </div>
        </div>
      )}

      {/* SAM.gov Exclusion Banner — full-width, similar to OIG */}
      {samData?.excluded && (
        <div className="bg-red-950 border-2 border-red-600 rounded-xl px-6 py-5 flex items-start gap-4 shadow-lg shadow-red-950/50" style={{ animation: 'threat-pulse-bg 2.5s ease-in-out infinite' }}>
          <span className="text-red-500 text-3xl mt-0.5 font-black">{'\u26D4'}</span>
          <div className="flex-1">
            <p className="text-red-300 font-black text-base uppercase tracking-wider">SAM.GOV FEDERAL EXCLUSION -- PROVIDER EXCLUDED FROM GOVERNMENT CONTRACTS</p>
            <p className="text-red-400 text-sm mt-2">
              Found {samData.records.length} exclusion record{samData.records.length !== 1 ? 's' : ''} on the System for Award Management federal exclusion list.
            </p>
          </div>
        </div>
      )}

      {/* Header — tinted red for high-risk providers */}
      <div className={`card flex items-start justify-between gap-4 ${
        detail.risk_score >= 50 ? 'border-red-800 bg-red-950/20' : ''
      }`}>
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold text-white">{nppes.name || `NPI ${npi}`}</h1>
            <span className="text-xs px-2 py-0.5 bg-gray-800 border border-gray-700 rounded-full text-gray-400">
              {nppes.entity_type === 'NPI-2' ? 'Organization' : 'Individual'}
            </span>
            {oigData?.loaded && !oigExcluded && (
              <span className="text-xs px-2 py-0.5 bg-green-900/40 border border-green-800 rounded-full text-green-400">
                Not on OIG List
              </span>
            )}
            {samData && !samData.excluded && !samData.error && (
              <span className="text-xs px-2 py-0.5 bg-green-900/40 border border-green-800 rounded-full text-green-400">
                SAM.gov CLEAR
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 mt-2 text-sm text-gray-400 flex-wrap">
            <span className="font-mono-data text-blue-400">{npi}</span>
            {addr.city && <span>{addr.city}, {addr.state} {addr.zip}</span>}
            {tax.description && <span className="text-purple-400">{tax.description}</span>}
          </div>
          {nppes.authorized_official?.name && (
            <p className="text-xs text-gray-500 mt-1">
              Auth. Official: {nppes.authorized_official.name} · {nppes.authorized_official.title}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-3 no-print">
          <div className="text-center">
            <p className="text-xs text-gray-500 uppercase tracking-widest font-bold mb-1">RISK SCORE</p>
            <RiskScoreBadge score={detail.risk_score} size="lg" />
            <div className="flex items-center justify-center gap-1 mt-1">
              <RiskScoreModal />
            </div>
          </div>
          <button
            onClick={() => api.exportProvider(npi!)}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 hover:border-gray-500 text-gray-200 text-sm font-medium rounded transition-colors flex items-center gap-2"
            title="Download all fraud evidence for this provider as a .tar.gz archive"
          >
            <span>&#8659;</span> Export Fraud Package
          </button>
        </div>
      </div>

      {/* Quick Stats bar */}
      <div className="card p-0 flex divide-x divide-gray-800">
        {[
          { label: 'Total Paid',    value: fmt(detail.spending?.total_paid ?? 0),                            color: 'text-blue-400' },
          { label: 'Total Claims',  value: (detail.spending?.total_claims ?? 0).toLocaleString(),             color: 'text-purple-400' },
          { label: 'Beneficiaries', value: (detail.spending?.total_beneficiaries ?? 0).toLocaleString(),      color: 'text-green-400' },
          { label: 'Active Months', value: detail.spending?.active_months ?? 0,                               color: 'text-yellow-400' },
          { label: 'Fraud Signals', value: `${(detail.signal_results ?? []).filter(s => s.flagged).length} / ${(detail.signal_results ?? []).length}`, color: (detail.signal_results ?? []).some(s => s.flagged) ? 'text-red-400' : 'text-green-400' },
          { label: 'Avg $/Claim',   value: detail.spending?.total_claims ? fmt(Math.round((detail.spending?.total_paid ?? 0) / detail.spending.total_claims)) : '--', color: 'text-cyan-400' },
        ].map(kpi => (
          <div key={kpi.label} className="flex-1 px-5 py-4 text-center">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{kpi.label}</p>
            <p className={`text-xl font-bold mt-1 ${kpi.color}`}>{kpi.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-5">
        {/* Fraud flags */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">
            {(detail.signal_results ?? []).length} Fraud Signals Analyzed
          </h2>
          <FraudFlagsTable signals={detail.signal_results ?? []} />
        </div>

        {/* HCPCS breakdown */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Billing by Procedure Code</h2>
          {hcpcsData?.hcpcs?.length ? (
            <HcpcsBreakdown data={hcpcsData.hcpcs} />
          ) : (
            <div className="h-40 flex items-center justify-center text-gray-600 text-sm">Loading…</div>
          )}
        </div>
      </div>

      {/* Peer Comparison */}
      {peers && peers.top_hcpcs && peers.peer_count > 0 && (
        <div className="card bg-blue-950/20 border-blue-900/40">
          <h2 className="text-sm font-semibold text-gray-300 mb-1">Peer Comparison</h2>
          <p className="text-xs text-gray-500 mb-3">
            Compared to <span className="text-gray-300 font-medium">{peers.peer_count.toLocaleString()}</span> providers
            billing primarily <span className="font-mono text-blue-400">{peers.top_hcpcs}</span>
          </p>
          <table className="w-full">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="text-left pb-2 pr-4 font-medium">Metric</th>
                <th className="text-left pb-2 pr-4 font-medium">This Provider</th>
                <th className="text-left pb-2 pr-4 font-medium">Peer Median</th>
                <th className="text-left pb-2 pr-4 font-medium">Peer 90th %ile</th>
                <th className="text-left pb-2 font-medium">Rank</th>
              </tr>
            </thead>
            <tbody>
              <PeerRow
                label="Revenue / Beneficiary"
                value={peers.this_provider.revenue_per_beneficiary}
                stats={peers.rpb_stats}
                pct={peers.percentiles.revenue_per_beneficiary}
              />
              <PeerRow
                label="Claims / Beneficiary"
                value={peers.this_provider.claims_per_beneficiary}
                stats={peers.cpb_stats}
                pct={peers.percentiles.claims_per_beneficiary}
                money={false}
              />
              <PeerRow
                label="Total Paid"
                value={peers.this_provider.total_paid}
                stats={peers.paid_stats}
                pct={peers.percentiles.total_paid}
              />
            </tbody>
          </table>
        </div>
      )}

      {/* Same-address cluster */}
      {cluster.length > 0 && (
        <div className="card border-yellow-800/50">
          <div className="flex items-start gap-2 mb-3">
            <span className="text-yellow-400 text-lg">⚠</span>
            <div>
              <h2 className="text-sm font-semibold text-yellow-300">
                {cluster.length} Other Provider{cluster.length !== 1 ? 's' : ''} at Same Address
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {clusterData?.address?.line1}, {clusterData?.address?.city}, {clusterData?.address?.state} {clusterData?.address?.zip}
              </p>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="text-left pb-2 pr-4 font-medium">NPI</th>
                <th className="text-left pb-2 pr-4 font-medium">Name</th>
                <th className="text-left pb-2 pr-4 font-medium">Specialty</th>
                <th className="text-left pb-2 pr-4 font-medium">Risk</th>
                <th className="text-left pb-2 pr-4 font-medium">Total Paid</th>
                <th className="text-left pb-2 font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {cluster.map((c: ClusterProvider) => (
                <tr key={c.npi} className="border-b border-gray-800 hover:bg-gray-800/30">
                  <td className="py-2 pr-4">
                    <Link to={`/providers/${c.npi}`} className="font-mono text-xs text-blue-400 hover:text-blue-300 underline">
                      {c.npi}
                    </Link>
                  </td>
                  <td className="py-2 pr-4 text-gray-300 max-w-[180px] truncate text-xs" title={c.provider_name}>
                    {c.provider_name || '—'}
                  </td>
                  <td className="py-2 pr-4 text-gray-500 text-xs max-w-[160px] truncate" title={c.specialty}>
                    {c.specialty || '—'}
                  </td>
                  <td className="py-2 pr-4">
                    <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
                      c.risk_score >= 75 ? 'bg-red-900 text-red-300' :
                      c.risk_score >= 50 ? 'bg-orange-900 text-orange-300' :
                      'bg-gray-800 text-gray-400'
                    }`}>{c.risk_score.toFixed(0)}</span>
                  </td>
                  <td className="py-2 pr-4 text-gray-400 text-xs">{fmt(c.total_paid)}</td>
                  <td className="py-2 text-xs">
                    {c.flag_count > 0
                      ? <span className="text-red-400">{c.flag_count} flag{c.flag_count !== 1 ? 's' : ''}</span>
                      : <span className="text-gray-600">—</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Open Payments + SAM.gov Exclusion Cards */}
      <div className="grid grid-cols-2 gap-5">
        {/* CMS Open Payments Card */}
        <div className={`card ${
          openPaymentsData?.total_amount && openPaymentsData.total_amount >= 100_000
            ? 'border-red-800 bg-red-950/20'
            : openPaymentsData?.total_amount && openPaymentsData.total_amount >= 10_000
              ? 'border-yellow-800 bg-yellow-950/20'
              : ''
        }`}>
          <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            CMS Open Payments
            {openPaymentsData?.total_amount && openPaymentsData.total_amount >= 100_000 && (
              <span className="text-xs px-2 py-0.5 bg-red-900 border border-red-700 rounded-full text-red-300 font-bold">
                HIGH INDUSTRY PAYMENTS
              </span>
            )}
            {openPaymentsData?.total_amount && openPaymentsData.total_amount >= 10_000 && openPaymentsData.total_amount < 100_000 && (
              <span className="text-xs px-2 py-0.5 bg-yellow-900 border border-yellow-700 rounded-full text-yellow-300 font-bold">
                NOTABLE PAYMENTS
              </span>
            )}
          </h2>
          {openPaymentsData ? (
            (openPaymentsData as any).unavailable ? (
              <div className="space-y-2">
                <p className="text-sm text-gray-400">{(openPaymentsData as any).message}</p>
                <a
                  href={(openPaymentsData as any).lookup_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block text-xs px-3 py-1.5 bg-blue-900/40 border border-blue-700 rounded text-blue-400 hover:bg-blue-900/60 transition-colors"
                >
                  Search on CMS Open Payments &rarr;
                </a>
              </div>
            ) : openPaymentsData.error ? (
              <p className="text-xs text-gray-500">Could not reach Open Payments API: {openPaymentsData.error}</p>
            ) : openPaymentsData.has_payments ? (
              <div className="space-y-3">
                <div className="flex items-baseline gap-6">
                  <div>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Total Received</p>
                    <p className={`text-xl font-bold mt-0.5 ${
                      openPaymentsData.total_amount >= 100_000 ? 'text-red-400' :
                      openPaymentsData.total_amount >= 10_000 ? 'text-yellow-400' : 'text-blue-400'
                    }`}>
                      {fmt(openPaymentsData.total_amount)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Payments</p>
                    <p className="text-xl font-bold mt-0.5 text-gray-300">{openPaymentsData.payment_count}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Companies</p>
                    <p className="text-xl font-bold mt-0.5 text-gray-300">{openPaymentsData.unique_companies.length}</p>
                  </div>
                </div>
                {openPaymentsData.unique_companies.length > 0 && (
                  <div>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Paying Companies</p>
                    <div className="flex flex-wrap gap-1">
                      {openPaymentsData.unique_companies.map(c => (
                        <span key={c} className="text-xs px-2 py-0.5 bg-gray-800 border border-gray-700 rounded text-gray-400">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">No industry payments found in CMS Open Payments database.</p>
            )
          ) : (
            <div className="h-16 flex items-center justify-center text-gray-600 text-sm">Loading...</div>
          )}
        </div>

        {/* SAM.gov Exclusion Detail Card */}
        <div className={`card ${
          samData?.excluded ? 'border-red-800 bg-red-950/20' : ''
        }`}>
          <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            SAM.gov Federal Exclusion
            {samData && !samData.excluded && !samData.error && (
              <span className="text-xs px-2 py-0.5 bg-green-900/40 border border-green-800 rounded-full text-green-400 font-bold">
                CLEAR
              </span>
            )}
            {samData?.excluded && (
              <span className="text-xs px-2 py-0.5 bg-red-900 border border-red-700 rounded-full text-red-300 font-bold">
                EXCLUDED
              </span>
            )}
          </h2>
          {samData ? (
            samData.error ? (
              <div className="space-y-2">
                <p className="text-xs text-gray-400">{samData.error}</p>
                {samData.error.includes('SAM_API_KEY') && (
                  <a
                    href="https://sam.gov/profile/details"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block text-xs px-3 py-1.5 bg-blue-900/40 border border-blue-700 rounded text-blue-400 hover:bg-blue-900/60 transition-colors"
                  >
                    Get free API key at SAM.gov &rarr;
                  </a>
                )}
              </div>
            ) : samData.excluded ? (
              <div className="space-y-2">
                <p className="text-sm text-red-400">
                  This provider was found on the SAM.gov federal exclusion list. Excluded entities are barred from receiving federal contracts and certain types of federal financial assistance.
                </p>
                {samData.records.length > 0 && (
                  <div>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Exclusion Records ({samData.records.length})</p>
                    <div className="space-y-1">
                      {samData.records.map((r, i) => (
                        <div key={i} className="text-xs bg-red-950/40 border border-red-900 rounded px-3 py-2 text-red-300 font-mono">
                          {Object.entries(r).slice(0, 4).map(([k, v]) => (
                            <span key={k} className="mr-3 inline-block">
                              {String(k).toUpperCase()}: {String(v)}
                            </span>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">
                Not found on the SAM.gov federal exclusion list. This provider is not currently barred from federal contracts.
              </p>
            )
          ) : (
            <div className="h-16 flex items-center justify-center text-gray-600 text-sm">Loading...</div>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Monthly Billing Timeline</h2>
        {timelineData?.timeline?.length ? (
          <SpendingTimeline data={timelineData.timeline} />
        ) : (
          <div className="h-64 flex items-center justify-center text-gray-600 text-sm">Loading…</div>
        )}
      </div>

      {/* Network link */}
      <div className="card flex items-center justify-between no-print">
        <div>
          <h2 className="text-sm font-semibold text-gray-300">Provider Network</h2>
          <p className="text-xs text-gray-500 mt-0.5">Explore billing/servicing relationships for this NPI</p>
        </div>
        <Link to={`/network?npi=${npi}`} className="btn-primary">
          View Network →
        </Link>
      </div>
    </div>
  )
}
