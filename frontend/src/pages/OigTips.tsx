import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import Breadcrumbs from '../components/Breadcrumbs'
import Magnitude from '../components/Magnitude'
import type { OigTip } from '../lib/types'

const STATUSES: OigTip['status'][] = ['filed', 'acknowledged', 'under_review', 'action_taken', 'no_action', 'closed']
const STATUS_TONE: Record<string, string> = {
  filed: 'text-ink-secondary',
  acknowledged: 'text-filament-core',
  under_review: 'text-filament-core',
  action_taken: 'text-threat-clear',
  no_action: 'text-ink-tertiary',
  closed: 'text-ink-tertiary',
}

export default function OigTips() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['oig-tips'],
    queryFn: () => api.oigTipsList(),
    staleTime: 60_000,
  })

  // ?channel=doj|oig so a filtered view can be linked and survives a reload.
  const [params, setParams] = useSearchParams()
  const channel = (['doj', 'oig'].includes(params.get('channel') ?? '') ? params.get('channel') : 'all') as 'all' | 'doj' | 'oig'
  const setChannel = (c: 'all' | 'doj' | 'oig') => setParams(c === 'all' ? {} : { channel: c }, { replace: true })
  const tips = useMemo(
    () => (data?.tips ?? []).filter(t => channel === 'all' || (t.destination ?? 'oig') === channel),
    [data, channel],
  )
  const statusCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const t of tips) c[t.status] = (c[t.status] ?? 0) + 1
    return c
  }, [tips])

  async function patch(id: string, body: Parameters<typeof api.updateOigTip>[1]) {
    await api.updateOigTip(id, body)
    qc.invalidateQueries({ queryKey: ['oig-tips'] })
    qc.invalidateQueries({ queryKey: ['oig-tips-filed'] })
  }

  return (
    <div className="space-y-5">
      <Breadcrumbs />
      <div>
        <h1 className="text-xl font-display font-bold text-ink-primary tracking-tight">Federal Tips &mdash; OIG &amp; DOJ</h1>
        <p className="text-sm text-ink-tertiary mt-1 max-w-3xl leading-relaxed">
          Every tip you've filed with the HHS-OIG Hotline or the DOJ Criminal Tip Rewards portal
          (america.gov/fraud), its lifecycle, and outcome.
          {data?.counts.by_destination && (
            <span className="font-mono tabular-nums">
              {' '}OIG {data.counts.by_destination.oig ?? 0} &middot; DOJ {data.counts.by_destination.doj ?? 0}
            </span>
          )}
        </p>
      </div>

      <div className="card border-amber-400/30 bg-amber-400/5">
        <p className="text-xs text-ink-secondary leading-relaxed">
          <span className="text-amber-300 font-semibold">DOJ tips:</span> the portal shows a reference number
          when you submit &mdash; record it in Ref #. DOJ contacts eligible tipsters after charges are unsealed;
          a reward ($10,000&ndash;$30,000 per distinct tip) is discretionary and not guaranteed.
        </p>
      </div>

      <div className="card border-filament-dim/40 bg-filament-core/5">
        <p className="text-xs text-ink-secondary leading-relaxed">
          <span className="text-filament-core font-semibold">Reality of OIG Hotline tracking:</span> OIG
          does <strong>not</strong> confirm receipt or report status on complaints. The statuses below are
          <em> self-tracked</em> — only reachable if an OIG official proactively contacts you. The one way to
          learn an outcome is a FOIA request to the OIG FOIA officer (phrased as “records pertinent to my
          complaint,” not “status”), filed no sooner than <strong>6 months</strong> after submission — see each
          tip's FOIA-eligible date.
        </p>
      </div>

      {data && (
        <div className="inline-flex rounded border border-hairline overflow-hidden">
          {([
            ['all', `All (${data.tips.length})`],
            ['doj', `DOJ (${data.counts.by_destination?.doj ?? 0})`],
            ['oig', `OIG (${data.counts.by_destination?.oig ?? 0})`],
          ] as const).map(([key, label], i) => (
            <button
              key={key}
              onClick={() => setChannel(key)}
              className={`px-3 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors ${i ? 'border-l border-hairline' : ''} ${
                channel === key
                  ? key === 'doj' ? 'bg-amber-400/10 text-amber-300' : key === 'oig' ? 'bg-teal-400/10 text-teal-300' : 'bg-surface-2 text-filament-core'
                  : 'text-ink-tertiary hover:text-ink-secondary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {data && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
          {STATUSES.map((s) => (
            <div key={s} className="card py-2.5">
              <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.12em]">{s.replace('_', ' ')}</p>
              <p className={`text-lg font-mono tabular-nums ${STATUS_TONE[s]}`}>{statusCounts[s] ?? 0}</p>
            </div>
          ))}
        </div>
      )}

      {isLoading && <div className="card h-24 flex items-center justify-center text-ink-tertiary text-sm font-mono">Loading tips…</div>}
      {error != null && <div className="card border-threat-critical/60"><p className="text-sm text-threat-high">Failed to load: {String(error)}</p></div>}
      {data && data.tips.length === 0 && (
        <div className="card">
          <p className="text-sm text-ink-tertiary">
            No tips logged yet. Open a provider, generate an <span className="text-filament-core">OIG Hotline Tip</span> or
            a <span className="text-amber-300">DOJ Tip</span>, and click “Log as filed” after you submit it.
          </p>
        </div>
      )}

      {data && data.tips.length > 0 && tips.length === 0 && (
        <div className="card"><p className="text-sm text-ink-tertiary">No {channel.toUpperCase()} tips logged yet.</p></div>
      )}

      {tips.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] text-ink-tertiary uppercase tracking-[0.14em] border-b border-hairline">
                <th className="py-2 pr-4">Provider</th>
                <th className="py-2 pr-4">Channel</th>
                <th className="py-2 pr-4">Risk</th>
                <th className="py-2 pr-4">Filed</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Ref #</th>
                <th className="py-2">Outcome notes</th>
              </tr>
            </thead>
            <tbody>
              {tips.map((t) => (
                <tr key={t.id} className="border-b border-hairline/60 hover:bg-surface-2/40">
                  <td className="py-2 pr-4">
                    <Link to={`/providers/${t.npi}`} className="text-filament-core hover:underline">{t.provider_name || t.npi}</Link>
                    <span className="block font-mono text-[11px] text-ink-tertiary">{t.npi}{t.state ? ` · ${t.state}` : ''}</span>
                    {t.filed_text && (
                      <details className="mt-1">
                        <summary className="text-[11px] text-ink-tertiary cursor-pointer hover:text-ink-secondary">Text as filed</summary>
                        <pre className="mt-1 max-h-64 max-w-xl overflow-auto whitespace-pre-wrap text-[11px] text-ink-secondary bg-surface-2 border border-hairline rounded p-2">{t.filed_text}</pre>
                      </details>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {(t.destination ?? 'oig') === 'doj' ? (
                      <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border border-amber-400/50 bg-amber-400/10 text-amber-300">DOJ</span>
                    ) : (
                      <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border border-teal-400/50 bg-teal-400/10 text-teal-300">OIG</span>
                    )}
                  </td>
                  <td className="py-2 pr-4"><Magnitude score={t.risk_score} size="sm" /></td>
                  <td className="py-2 pr-4 font-mono text-xs text-ink-tertiary">
                    {new Date(t.filed_at * 1000).toLocaleDateString()}
                    {t.foia_eligible_at && (
                      <span
                        className="block text-[10px] text-ink-ghost"
                        title="Earliest date to file a FOIA records request about this complaint"
                      >
                        FOIA: {new Date(t.foia_eligible_at * 1000).toLocaleDateString()}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <select
                      value={t.status}
                      onChange={(e) => patch(t.id, { status: e.target.value as OigTip['status'] })}
                      className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs font-mono text-ink-secondary"
                    >
                      {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                    </select>
                  </td>
                  <td className="py-2 pr-4">
                    <input
                      defaultValue={t.reference_number}
                      onBlur={(e) => { if (e.target.value !== t.reference_number) patch(t.id, { reference_number: e.target.value }) }}
                      placeholder="—"
                      className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs font-mono text-ink-secondary w-48"
                    />
                  </td>
                  <td className="py-2">
                    <input
                      defaultValue={t.outcome_notes}
                      onBlur={(e) => { if (e.target.value !== t.outcome_notes) patch(t.id, { outcome_notes: e.target.value }) }}
                      placeholder="—"
                      className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs text-ink-secondary w-full min-w-[180px]"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
