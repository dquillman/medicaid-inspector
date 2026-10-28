import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import DojTipPanel, { dojTipQueryKey } from '../components/DojTipPanel'

/**
 * DOJ Criminal Tip Rewards Pilot Program — the third referral destination,
 * next to OIG and MFCU. Same ONE generator (`/oig-tip?destination=doj`): the
 * evidence body is identical; only the routing header/footer, the short
 * first-box version and the filing guide differ.
 *
 * The filing content lives in DojTipPanel, shared with Filing mode, so the
 * single-provider page and the walk-the-shortlist flow can never drift.
 */
export default function DojReferralPage() {
  const { npi } = useParams<{ npi: string }>()

  const { data: provider } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })
  const providerName = provider?.nppes?.name ?? provider?.provider_name ?? `NPI ${npi}`
  const riskScore = provider?.risk_score ?? 0
  const providerState = provider?.state ?? provider?.nppes?.address?.state ?? ''

  // Same cache entry the panel fills — read here only for the header badge
  // and the summary card.
  const { data: tip } = useQuery({
    queryKey: dojTipQueryKey(npi ?? ''),
    queryFn: () => api.oigTip(npi!, 'doj'),
    enabled: !!npi,
    staleTime: 5 * 60_000,
  })
  const priority = tip?.doj_priority

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/providers" className="hover:text-gray-300">Providers</Link>
        <span>/</span>
        <Link to={`/providers/${npi}`} className="hover:text-gray-300 font-mono">{npi}</Link>
        <span>/</span>
        <span className="text-gray-300">DOJ Tip (Rewards)</span>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-white font-bold text-xl flex items-center gap-2">
            DOJ Tip &mdash; Criminal Tip Rewards
            {priority?.priority && (
              <span
                className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border border-amber-400/60 bg-amber-400/10 text-amber-300"
                title={`DOJ names ${priority.area.toLowerCase()} as a priority fraud area (taxonomy: ${priority.taxonomy})`}
              >
                DOJ priority &middot; {priority.area}
              </span>
            )}
          </h1>
          <p className="text-gray-400 text-sm mt-0.5">{providerName}</p>
        </div>
        <Link to={`/providers/${npi}`} className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1">
          &larr; Back to Provider
        </Link>
      </div>

      <p className="text-xs text-amber-200 border-l-2 border-amber-700 pl-3">
        Review the evidence before filing. Aggregate anomalies and administrative status matches
        do not establish fraud. Verify identity, Medicaid applicability, effective dates, and
        alternative explanations; payment totals are not confirmed losses. Unknown checks remain unresolved.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          {npi && (
            <DojTipPanel
              npi={npi}
              providerName={providerName}
              providerState={providerState}
              riskScore={riskScore}
              actions={
                <Link to={`/providers/${npi}`} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors">
                  Back to Provider
                </Link>
              }
            />
          )}
        </div>

        <div className="space-y-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-5 sticky top-20">
            <h3 className="text-gray-300 text-xs font-semibold uppercase tracking-wider mb-3">Provider Summary</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Risk Score</span>
                <span className="text-sm font-bold font-mono tabular-nums text-gray-200">{riskScore}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Total Paid</span>
                <span className="text-white text-sm font-mono tabular-nums">{fmt(provider?.spending?.total_paid ?? 0)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Signals fired</span>
                <span className="text-white text-sm font-mono tabular-nums">{tip?.signal_count ?? '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">DOJ priority area</span>
                <span className="text-xs text-amber-300">{priority?.priority ? priority.area : 'No'}</span>
              </div>
            </div>
            <div className="mt-4 pt-3 border-t border-gray-700 space-y-1.5">
              <Link to="/doj-filing" className="block text-xs text-amber-300 hover:text-amber-200">DOJ Filing mode (whole shortlist) &rarr;</Link>
              <Link to={`/providers/${npi}/oig-referral`} className="block text-xs text-blue-400 hover:text-blue-300">OIG Hotline tip &rarr;</Link>
              <Link to={`/providers/${npi}/referral`} className="block text-xs text-blue-400 hover:text-blue-300">State MFCU referral &rarr;</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
