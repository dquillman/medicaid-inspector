import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { api } from '../lib/api'
import RiskScoreBadge from '../components/RiskScoreBadge'
import SpendingTimeline from '../components/SpendingTimeline'
import HcpcsBreakdown from '../components/HcpcsBreakdown'
import FraudFlagsTable from '../components/FraudFlagsTable'
import RiskScoreModal from '../components/RiskScoreModal'
import ProviderTimelineAnalysis from '../components/ProviderTimelineAnalysis'
import SpecialtyBenchmark from '../components/SpecialtyBenchmark'
import TemporalAnalysisSection from '../components/TemporalAnalysisSection'
import type { ClusterProvider, OpenPaymentsData, SamExclusion, RelatedProvider, MedicareComparison, LicenseVerification } from '../lib/types'

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

function MedicareCrossReference({ data: medicareData }: { data: MedicareComparison | undefined }) {
  if (!medicareData) {
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Medicare Cross-Reference</h2>
        <div className="h-24 flex items-center justify-center text-gray-600 text-sm">Loading Medicare data...</div>
      </div>
    )
  }
  return (
    <div className={`card ${medicareData.has_discrepancies ? 'border-orange-800/60 bg-orange-950/10' : ''}`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
          Medicare Cross-Reference
          {medicareData.has_discrepancies && (
            <span className="text-xs px-2 py-0.5 bg-orange-900 border border-orange-700 rounded-full text-orange-300 font-bold">
              {medicareData.discrepancy_count} DISCREPANC{medicareData.discrepancy_count !== 1 ? 'IES' : 'Y'}
            </span>
          )}
          {!medicareData.medicare_has_data && !medicareData.error && (
            <span className="text-xs px-2 py-0.5 bg-gray-800 border border-gray-700 rounded-full text-gray-400">NO MEDICARE DATA</span>
          )}
        </h2>
        <span className="text-[10px] text-gray-600 uppercase tracking-wider">CMS Medicare FFS Utilization</span>
      </div>
      {medicareData.error ? (
        <p className="text-xs text-gray-500">Could not reach CMS Medicare API: {medicareData.error}</p>
      ) : (
        <div className="space-y-4">
          {medicareData.discrepancies.length > 0 && (
            <div className="space-y-2">
              {medicareData.discrepancies.map((d, i) => {
                const alertCls = d.severity === 'HIGH' ? 'bg-red-950/30 border-red-800 text-red-300' : d.severity === 'MEDIUM' ? 'bg-orange-950/30 border-orange-800 text-orange-300' : 'bg-yellow-950/30 border-yellow-800 text-yellow-300'
                return (
                  <div key={i} className={`flex items-start gap-3 px-4 py-3 rounded-lg border ${alertCls}`}>
                    <span className="text-lg mt-0.5 font-black">{d.severity === 'LOW' ? '\u2139' : '\u26A0'}</span>
                    <div className="flex-1">
                      <p className="text-sm font-medium">{d.description}</p>
                      <p className="text-xs mt-0.5 opacity-70">
                        {d.type === 'billing_ratio' && 'Disproportionate Medicaid billing relative to Medicare may indicate Medicaid-specific fraud patterns.'}
                        {d.type === 'beneficiary_ratio' && 'Large disparity in patient populations between programs warrants further review.'}
                        {d.type === 'per_bene_spending' && 'Elevated per-beneficiary spending in Medicaid vs Medicare suggests possible upcoding or overutilization.'}
                        {d.type === 'no_medicare_data' && 'Provider has significant Medicaid billing but no Medicare footprint.'}
                      </p>
                    </div>
                    {d.ratio != null && <span className={`flex-shrink-0 text-lg font-bold font-mono ${d.severity === 'HIGH' ? 'text-red-400' : 'text-orange-400'}`}>{d.ratio}x</span>}
                  </div>
                )
              })}
            </div>
          )}
          <div>
            <h3 className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-2">Program Comparison</h3>
            <table className="w-full text-sm">
              <thead><tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="text-left pb-2 pr-4 font-medium">Metric</th>
                <th className="text-left pb-2 pr-4 font-medium">Medicaid</th>
                <th className="text-left pb-2 pr-4 font-medium">Medicare</th>
                <th className="text-left pb-2 font-medium">Ratio</th>
              </tr></thead>
              <tbody>
                {([
                  { label: 'Total Paid', medicaid: medicareData.medicaid.total_paid, medicare: medicareData.medicare.total_paid, money: true },
                  { label: 'Claims / Services', medicaid: medicareData.medicaid.total_claims ?? 0, medicare: medicareData.medicare.total_services ?? 0, money: false },
                  { label: 'Beneficiaries', medicaid: medicareData.medicaid.total_beneficiaries, medicare: medicareData.medicare.total_beneficiaries, money: false },
                  { label: 'Avg per Beneficiary', medicaid: medicareData.medicaid.avg_per_bene, medicare: medicareData.medicare.avg_per_bene, money: true },
                ] as const).map(row => {
                  const ratio = row.medicare > 0 ? row.medicaid / row.medicare : null
                  const rc = ratio != null && ratio > 3 ? 'text-red-400' : ratio != null && ratio > 1.5 ? 'text-orange-400' : 'text-gray-400'
                  return (
                    <tr key={row.label} className="border-b border-gray-800">
                      <td className="py-2 pr-4 text-gray-400">{row.label}</td>
                      <td className="py-2 pr-4 font-mono text-white">{row.money ? fmt(row.medicaid) : row.medicaid.toLocaleString()}</td>
                      <td className="py-2 pr-4 font-mono text-gray-300">{medicareData.medicare_has_data ? (row.money ? fmt(row.medicare) : row.medicare.toLocaleString()) : <span className="text-gray-600">--</span>}</td>
                      <td className={`py-2 font-mono font-bold ${rc}`}>{ratio != null ? `${ratio.toFixed(1)}x` : '--'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {(medicareData.medicaid.top_hcpcs.length > 0 || medicareData.medicare.top_hcpcs.length > 0) && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h3 className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-2">Top Medicaid HCPCS</h3>
                {medicareData.medicaid.top_hcpcs.length > 0 ? (
                  <div className="space-y-1">
                    {medicareData.medicaid.top_hcpcs.slice(0, 5).map((h, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-1.5 bg-gray-900/50 border border-gray-800 rounded text-xs">
                        <span className="font-mono text-blue-400">{h.hcpcs_code}</span>
                        <span className="text-gray-300 font-mono">{fmt(h.total_paid)}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="text-xs text-gray-600">No data</p>}
              </div>
              <div>
                <h3 className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-2">Top Medicare HCPCS</h3>
                {medicareData.medicare_has_data && medicareData.medicare.top_hcpcs.length > 0 ? (
                  <div className="space-y-1">
                    {medicareData.medicare.top_hcpcs.slice(0, 5).map((h, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-1.5 bg-gray-900/50 border border-gray-800 rounded text-xs">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-mono text-green-400 flex-shrink-0">{h.hcpcs_code}</span>
                          {'description' in h && h.description && <span className="text-gray-500 truncate text-[10px]" title={String(h.description)}>{String(h.description)}</span>}
                        </div>
                        <span className="text-gray-300 font-mono flex-shrink-0 ml-2">{fmt(h.total_paid)}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="text-xs text-gray-600">{medicareData.medicare_has_data ? 'No data' : 'No Medicare data available'}</p>}
              </div>
            </div>
          )}
          {medicareData.medicare.provider_type && (
            <p className="text-xs text-gray-500">Medicare Provider Type: <span className="text-gray-400">{medicareData.medicare.provider_type}</span></p>
          )}
        </div>
      )}
    </div>
  )
}

export default function ProviderDetail() {
  const { npi } = useParams<{ npi: string }>()
  const queryClient = useQueryClient()
  const [watchlistMsg, setWatchlistMsg] = useState('')

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

  const { data: relatedData } = useQuery({
    queryKey: ['related-providers', npi],
    queryFn: () => api.relatedProviders(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: medicareData } = useQuery<MedicareComparison>({
    queryKey: ['medicare-compare', npi],
    queryFn: () => api.medicareCompare(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: watchlistStatus } = useQuery({
    queryKey: ['watchlist-check', npi],
    queryFn: () => api.watchlistCheck(npi!),
    enabled: !!npi,
    staleTime: 30_000,
  })

  const { data: scoreTrendData } = useQuery({
    queryKey: ['score-trend', npi],
    queryFn: () => api.scoreTrend(npi!),
    enabled: !!npi,
    staleTime: 30_000,
  })

  const { data: licenseData } = useQuery<LicenseVerification>({
    queryKey: ['license', npi],
    queryFn: () => api.providerLicense(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const { data: providerNewsData } = useQuery({
    queryKey: ['provider-news', npi],
    queryFn: () => api.providerNews(npi!),
    enabled: !!npi,
    staleTime: 60_000,
  })

  const addToWatchlistMutation = useMutation({
    mutationFn: () => api.addToWatchlist({ npi: npi!, reason: 'Added from provider detail page' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist-check', npi] })
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      setWatchlistMsg('Added to watchlist')
      setTimeout(() => setWatchlistMsg(''), 3000)
    },
    onError: (e: Error) => {
      setWatchlistMsg(e.message)
      setTimeout(() => setWatchlistMsg(''), 3000)
    },
  })

  const removeFromWatchlistMutation = useMutation({
    mutationFn: () => api.removeFromWatchlist(npi!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist-check', npi] })
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      setWatchlistMsg('Removed from watchlist')
      setTimeout(() => setWatchlistMsg(''), 3000)
    },
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
            onClick={() => window.open(`/api/providers/${npi}/referral-packet`, '_blank')}
            className="px-4 py-2 bg-red-700 hover:bg-red-600 border border-red-500 hover:border-red-400 text-white text-sm font-semibold rounded transition-colors flex items-center gap-2 shadow-md shadow-red-900/30"
            title="Generate a comprehensive HTML referral packet for this provider"
          >
            <span>&#128196;</span> Generate Referral Packet
          </button>
          <button
            onClick={() => api.exportProvider(npi!)}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 hover:border-gray-500 text-gray-200 text-sm font-medium rounded transition-colors flex items-center gap-2"
            title="Download all fraud evidence for this provider as a .tar.gz archive"
          >
            <span>&#8659;</span> Export Fraud Package
          </button>
          {watchlistStatus?.watched ? (
            <button
              onClick={() => removeFromWatchlistMutation.mutate()}
              disabled={removeFromWatchlistMutation.isPending}
              className="px-4 py-2 bg-yellow-900/40 hover:bg-yellow-900/60 border border-yellow-700 text-yellow-300 text-sm font-medium rounded transition-colors flex items-center gap-2"
              title="Remove from watchlist"
            >
              <span>&#9733;</span> On Watchlist
            </button>
          ) : (
            <button
              onClick={() => addToWatchlistMutation.mutate()}
              disabled={addToWatchlistMutation.isPending}
              className="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 hover:border-yellow-600 text-gray-200 text-sm font-medium rounded transition-colors flex items-center gap-2"
              title="Add to watchlist for monitoring"
            >
              <span>&#9734;</span> Add to Watchlist
            </button>
          )}
          {watchlistMsg && (
            <span className="text-xs text-green-400">{watchlistMsg}</span>
          )}
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
          <FraudFlagsTable signals={detail.signal_results ?? []} npi={npi} />
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

      {/* Risk Score Trend */}
      {scoreTrendData && scoreTrendData.snapshot_count >= 2 && (
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-1">Risk Score Trend</h2>
          <p className="text-xs text-gray-500 mb-3">
            {scoreTrendData.snapshot_count} scan snapshots tracked
          </p>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={scoreTrendData.snapshots.map((s: any) => ({
              ...s,
              date: new Date(s.timestamp * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
            }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} />
              <YAxis domain={[0, 100]} tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                labelStyle={{ color: '#9ca3af' }}
                formatter={(v: number, name: string) => {
                  if (name === 'score') return [v.toFixed(1), 'Risk Score']
                  if (name === 'flags') return [v, 'Flags']
                  return [v, name]
                }}
              />
              <ReferenceLine y={50} stroke="#ef4444" strokeDasharray="5 5" label={{ value: 'High Risk', fill: '#ef4444', fontSize: 10 }} />
              <ReferenceLine y={10} stroke="#eab308" strokeDasharray="3 3" label={{ value: 'Flagged', fill: '#eab308', fontSize: 10 }} />
              <Line type="monotone" dataKey="score" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
              <Line type="monotone" dataKey="flags" stroke="#f59e0b" strokeWidth={1} strokeDasharray="4 2" dot={false} yAxisId={0} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Specialty Benchmark */}
      <SpecialtyBenchmark npi={npi!} />

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
            openPaymentsData.error ? (
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

      {/* Credentials & License Verification */}
      <div className={`card ${
        licenseData?.has_critical_flags ? 'border-red-800 bg-red-950/20' :
        licenseData && licenseData.flag_count > 0 ? 'border-yellow-800 bg-yellow-950/20' : ''
      }`}>
        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
          Credentials & License Verification
          {licenseData?.verified && licenseData.flag_count === 0 && (
            <span className="text-xs px-2 py-0.5 bg-green-900/40 border border-green-800 rounded-full text-green-400 font-bold">
              VERIFIED
            </span>
          )}
          {licenseData?.has_critical_flags && (
            <span className="text-xs px-2 py-0.5 bg-red-900 border border-red-700 rounded-full text-red-300 font-bold">
              CRITICAL FLAGS
            </span>
          )}
          {licenseData && licenseData.flag_count > 0 && !licenseData.has_critical_flags && (
            <span className="text-xs px-2 py-0.5 bg-yellow-900 border border-yellow-700 rounded-full text-yellow-300 font-bold">
              {licenseData.flag_count} FLAG{licenseData.flag_count !== 1 ? 'S' : ''}
            </span>
          )}
        </h2>
        {licenseData ? (
          licenseData.error ? (
            <p className="text-xs text-gray-500">{licenseData.error}</p>
          ) : (
            <div className="space-y-4">
              {/* Credential Flags / Warnings */}
              {licenseData.credential_flags.length > 0 && (
                <div className="space-y-2">
                  {licenseData.credential_flags.map((flag, i) => (
                    <div
                      key={i}
                      className={`rounded-lg px-4 py-3 border ${
                        flag.severity === 'critical'
                          ? 'bg-red-950/40 border-red-800 text-red-300'
                          : flag.severity === 'warning'
                          ? 'bg-yellow-950/40 border-yellow-800 text-yellow-300'
                          : 'bg-blue-950/40 border-blue-800 text-blue-300'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs font-bold uppercase px-1.5 py-0.5 rounded ${
                          flag.severity === 'critical'
                            ? 'bg-red-900 text-red-200'
                            : flag.severity === 'warning'
                            ? 'bg-yellow-900 text-yellow-200'
                            : 'bg-blue-900 text-blue-200'
                        }`}>
                          {flag.severity}
                        </span>
                        <span className="text-sm font-semibold">{flag.title}</span>
                      </div>
                      <p className="text-xs opacity-80">{flag.description}</p>
                    </div>
                  ))}
                </div>
              )}

              {/* Entity & Deactivation Status */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Entity Type</p>
                  <p className="text-sm text-gray-300">
                    {licenseData.entity_info?.entity_type_label || '---'}
                    {licenseData.entity_info?.is_sole_proprietor && (
                      <span className="ml-2 text-xs px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-gray-400">
                        Sole Proprietor
                      </span>
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">NPI Status</p>
                  <p className="text-sm">
                    {licenseData.deactivation_status?.is_deactivated ? (
                      <span className="text-red-400 font-bold">
                        DEACTIVATED
                        {licenseData.deactivation_status.deactivation_date && (
                          <span className="font-normal text-xs ml-1">
                            ({licenseData.deactivation_status.deactivation_date})
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-green-400">Active</span>
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Enumeration Date</p>
                  <p className="text-sm text-gray-300">{licenseData.enumeration_date || '---'}</p>
                </div>
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Primary Specialty</p>
                  <p className="text-sm text-purple-400">
                    {licenseData.taxonomy_match?.primary_specialty || '---'}
                  </p>
                </div>
              </div>

              {/* Taxonomy Match Info */}
              {licenseData.taxonomy_match && (
                <div className={`text-xs px-3 py-2 rounded border ${
                  licenseData.taxonomy_match.is_high_risk_taxonomy
                    ? 'bg-orange-950/30 border-orange-800 text-orange-300'
                    : 'bg-gray-800/50 border-gray-700 text-gray-400'
                }`}>
                  {licenseData.taxonomy_match.match_details}
                  {licenseData.taxonomy_match.is_high_risk_taxonomy && (
                    <span className="ml-2 font-bold text-orange-300">-- HIGH RISK CATEGORY</span>
                  )}
                </div>
              )}

              {/* License Details Table */}
              {licenseData.licenses.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">
                    Registered Licenses & Taxonomy Codes ({licenseData.licenses.length})
                  </p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-gray-500 border-b border-gray-800">
                        <th className="text-left pb-2 pr-4 font-medium">Taxonomy Code</th>
                        <th className="text-left pb-2 pr-4 font-medium">Description</th>
                        <th className="text-left pb-2 pr-4 font-medium">State</th>
                        <th className="text-left pb-2 pr-4 font-medium">License #</th>
                        <th className="text-left pb-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {licenseData.licenses.map((lic, i) => (
                        <tr key={i} className="border-b border-gray-800/50">
                          <td className="py-2 pr-4 font-mono text-xs text-blue-400">{lic.taxonomy_code}</td>
                          <td className="py-2 pr-4 text-gray-300 text-xs max-w-[200px] truncate" title={lic.taxonomy_description}>
                            {lic.taxonomy_description || '---'}
                          </td>
                          <td className="py-2 pr-4 text-gray-400 text-xs">{lic.state || '---'}</td>
                          <td className="py-2 pr-4 font-mono text-xs text-gray-300">{lic.license_number || '---'}</td>
                          <td className="py-2">
                            {lic.is_primary ? (
                              <span className="text-xs px-1.5 py-0.5 bg-blue-900/40 border border-blue-800 rounded text-blue-300 font-bold">
                                PRIMARY
                              </span>
                            ) : (
                              <span className="text-xs text-gray-600">Secondary</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        ) : (
          <div className="h-16 flex items-center justify-center text-gray-600 text-sm">Loading...</div>
        )}
      </div>

      {/* Enhanced Timeline Analysis */}
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">
          Provider Timeline Analysis
        </h2>
        <ProviderTimelineAnalysis npi={npi!} />
      </div>

      {/* Related Providers Auto-Discovery */}
      {relatedData && relatedData.related_providers.length > 0 && (
        <div className="card border-indigo-800/50">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                Related Providers
                <span className="text-xs px-2 py-0.5 bg-indigo-900/40 border border-indigo-800 rounded-full text-indigo-400 font-bold">
                  {relatedData.total} found
                </span>
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                Auto-discovered via shared billing relationships, addresses, and patient overlap
              </p>
            </div>
          </div>
          <div className="space-y-2">
            {relatedData.related_providers.map((rp: RelatedProvider) => (
              <div key={rp.npi} className="flex items-center gap-4 px-4 py-3 bg-gray-900/50 border border-gray-800 rounded-lg hover:bg-gray-800/50 transition-colors">
                {/* Strength score bar */}
                <div className="flex-shrink-0 w-12 text-center">
                  <div className={`text-sm font-bold font-mono ${
                    rp.strength_score >= 75 ? 'text-red-400' :
                    rp.strength_score >= 50 ? 'text-orange-400' :
                    rp.strength_score >= 25 ? 'text-yellow-400' : 'text-gray-400'
                  }`}>
                    {rp.strength_score}
                  </div>
                  <div className="w-full h-1.5 bg-gray-800 rounded-full mt-1 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        rp.strength_score >= 75 ? 'bg-red-500' :
                        rp.strength_score >= 50 ? 'bg-orange-500' :
                        rp.strength_score >= 25 ? 'bg-yellow-500' : 'bg-gray-600'
                      }`}
                      style={{ width: `${rp.strength_score}%` }}
                    />
                  </div>
                </div>

                {/* Provider info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Link to={`/providers/${rp.npi}`} className="font-mono text-xs text-blue-400 hover:text-blue-300 underline">
                      {rp.npi}
                    </Link>
                    <span className="text-sm text-gray-300 truncate max-w-[200px]" title={rp.name}>
                      {rp.name || '—'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1">
                    {rp.specialty && (
                      <span className="text-xs text-purple-400 truncate max-w-[180px]" title={rp.specialty}>
                        {rp.specialty}
                      </span>
                    )}
                    {rp.city && rp.state && (
                      <span className="text-xs text-gray-500">{rp.city}, {rp.state}</span>
                    )}
                  </div>
                </div>

                {/* Relationship badges */}
                <div className="flex flex-wrap gap-1 max-w-[220px]">
                  {rp.relationship_types.map(rt => {
                    const labels: Record<string, string> = {
                      shared_billing_org: 'Shared Billing',
                      shared_servicing_npi: 'Shared Servicing',
                      shared_patients: 'Shared Patients',
                      same_address: 'Same Address',
                      same_zip: 'Same Zip',
                    }
                    const colors: Record<string, string> = {
                      shared_billing_org: 'bg-blue-900/50 border-blue-700 text-blue-300',
                      shared_servicing_npi: 'bg-cyan-900/50 border-cyan-700 text-cyan-300',
                      shared_patients: 'bg-green-900/50 border-green-700 text-green-300',
                      same_address: 'bg-yellow-900/50 border-yellow-700 text-yellow-300',
                      same_zip: 'bg-gray-800 border-gray-600 text-gray-400',
                    }
                    return (
                      <span key={rt} className={`text-[10px] px-1.5 py-0.5 border rounded ${colors[rt] ?? 'bg-gray-800 border-gray-700 text-gray-400'}`}>
                        {labels[rt] ?? rt}
                      </span>
                    )
                  })}
                </div>

                {/* Shared count */}
                <div className="flex-shrink-0 text-right w-16">
                  <p className="text-xs text-gray-500">Shared</p>
                  <p className="text-sm font-mono text-gray-300">{rp.shared_count}</p>
                </div>

                {/* Risk + Paid */}
                <div className="flex-shrink-0 text-right w-20">
                  <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
                    rp.risk_score >= 75 ? 'bg-red-900 text-red-300' :
                    rp.risk_score >= 50 ? 'bg-orange-900 text-orange-300' :
                    rp.risk_score >= 25 ? 'bg-yellow-900/50 text-yellow-300' :
                    'bg-gray-800 text-gray-400'
                  }`}>{rp.risk_score?.toFixed(0) ?? '—'}</span>
                  <p className="text-xs text-gray-500 mt-1">{fmt(rp.total_paid)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Temporal Anomaly Detection */}
      <TemporalAnalysisSection npi={npi!} />

      {/* Medicare Cross-Reference */}
      <MedicareCrossReference data={medicareData} />

      {/* News & Legal Alerts */}
      {providerNewsData && providerNewsData.alerts.length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-300">News & Legal Alerts</h2>
            <Link to="/news" className="text-xs text-blue-400 hover:underline">View all alerts</Link>
          </div>
          <div className="space-y-2">
            {providerNewsData.alerts.slice(0, 5).map((alert: any) => {
              const catColors: Record<string, string> = {
                news: 'bg-blue-900/60 text-blue-300 border-blue-700',
                legal: 'bg-yellow-900/60 text-yellow-300 border-yellow-700',
                enforcement: 'bg-red-900/60 text-red-300 border-red-700',
                settlement: 'bg-green-900/60 text-green-300 border-green-700',
              }
              return (
                <div key={alert.id} className="flex items-start gap-3 px-3 py-2 bg-gray-800/50 rounded border border-gray-700">
                  <span className={`text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded border shrink-0 ${catColors[alert.category] ?? 'bg-gray-800 text-gray-400 border-gray-700'}`}>
                    {alert.category}
                  </span>
                  <div className="min-w-0 flex-1">
                    <a href={alert.url} target="_blank" rel="noopener noreferrer" className="text-xs font-semibold text-white hover:text-blue-300">
                      {alert.title}
                    </a>
                    <p className="text-[11px] text-gray-500 mt-0.5 truncate">{alert.summary}</p>
                  </div>
                  <span className="text-[10px] text-gray-600 shrink-0">{alert.date}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

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
