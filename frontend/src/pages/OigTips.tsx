import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import Breadcrumbs from '../components/Breadcrumbs'
import Magnitude from '../components/Magnitude'
import TipUpdatesCard from '../components/TipUpdatesCard'
import type { OigTip, MFCUReferral } from '../lib/types'

type Channel = 'oig' | 'doj' | 'mfcu'
const CHANNELS: Channel[] = ['oig', 'mfcu', 'doj']

/** One filing on one channel: an OIG/DOJ tip, or a state MFCU referral. */
interface Filing {
  id: string
  npi: string
  channel: Channel
  provider_name: string
  state: string
  risk_score: number
  filed_at: number
  tip?: OigTip
  referral?: MFCUReferral
}

const STATUSES: OigTip['status'][] = ['filed', 'acknowledged', 'under_review', 'action_taken', 'no_action', 'closed']
const STATUS_TONE: Record<string, string> = {
  filed: 'text-ink-secondary',
  acknowledged: 'text-filament-core',
  under_review: 'text-filament-core',
  action_taken: 'text-threat-clear',
  no_action: 'text-ink-tertiary',
  closed: 'text-ink-tertiary',
}

function ChannelBadge({ channel, dim, small, title }: { channel: string; dim?: boolean; small?: boolean; title?: string }) {
  const tone = channel === 'doj'
    ? 'border-amber-400/50 bg-amber-400/10 text-amber-300'
    : channel === 'mfcu'
      ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-300'
      : 'border-teal-400/50 bg-teal-400/10 text-teal-300'
  return (
    <span title={title}
      className={`${small ? 'text-[9px] px-1 py-0' : 'text-[10px] px-1.5 py-0.5'} font-mono uppercase tracking-wider rounded border ${tone} ${dim ? 'opacity-40' : ''}`}>
      {dim ? `also ${channel}` : channel}
    </span>
  )
}

export default function OigTips() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['oig-tips'],
    queryFn: () => api.oigTipsList(),
    staleTime: 60_000,
  })

  // State MFCU referrals live in their own store; a provider referred to its
  // state's MFCU must show that here too, next to its OIG/DOJ tips.
  const { data: refData } = useQuery({
    queryKey: ['mfcu-referrals'],
    queryFn: () => api.listReferrals(),
    staleTime: 60_000,
  })

  // ?channel=doj|oig|mfcu so a filtered view can be linked and survives a reload.
  const [params, setParams] = useSearchParams()
  const channel = ((CHANNELS as string[]).includes(params.get('channel') ?? '') ? params.get('channel') : 'all') as 'all' | Channel
  const setChannel = (c: 'all' | Channel) => setParams(c === 'all' ? {} : { channel: c }, { replace: true })

  const allFilings = useMemo<Filing[]>(() => [
    ...(data?.tips ?? []).map(t => ({
      id: t.id, npi: t.npi, channel: (t.destination ?? 'oig') as Channel,
      provider_name: t.provider_name, state: t.state, risk_score: t.risk_score,
      filed_at: t.filed_at, tip: t,
    })),
    // A draft was never sent; only filed referrals count.
    ...(refData?.referrals ?? []).filter(r => r.stage !== 'draft').map(r => ({
      id: `mfcu-${r.referral_id}`, npi: r.npi, channel: 'mfcu' as Channel,
      provider_name: r.provider_name ?? '', state: r.state ?? '', risk_score: r.risk_score ?? 0,
      filed_at: r.referral_date || r.created_at, referral: r,
    })),
  ], [data, refData])
  const channelCount = (c: Channel) => allFilings.filter(f => f.channel === c).length
  const filings = useMemo(
    () => allFilings.filter(f => channel === 'all' || f.channel === channel),
    [allFilings, channel],
  )
  const statusCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const f of filings) if (f.tip) c[f.tip.status] = (c[f.tip.status] ?? 0) + 1
    return c
  }, [filings])

  // One row per provider: a provider reported to OIG, its state MFCU and DOJ
  // shows every channel together instead of as unrelated rows. `channels` =
  // every channel it was filed to, so a single-channel view can still say "also".
  const groups = useMemo(() => {
    const channelsByNpi = new Map<string, Set<Channel>>()
    for (const f of allFilings) {
      if (!channelsByNpi.has(f.npi)) channelsByNpi.set(f.npi, new Set())
      channelsByNpi.get(f.npi)!.add(f.channel)
    }
    const shown = new Map<string, Filing[]>()
    for (const f of filings) {
      if (!shown.has(f.npi)) shown.set(f.npi, [])
      shown.get(f.npi)!.push(f)
    }
    return Array.from(shown.entries())
      .map(([npi, list]) => {
        const rows = [...list].sort((a, b) => a.filed_at - b.filed_at)
        return {
          npi,
          rows,
          latest: Math.max(...rows.map(r => r.filed_at || 0)),
          name: rows.find(r => r.provider_name)?.provider_name || npi,
          state: rows.find(r => r.state)?.state || '',
          risk: Math.max(...rows.map(r => r.risk_score || 0)),
          channels: CHANNELS.filter(c => channelsByNpi.get(npi)?.has(c)),
        }
      })
      .sort((a, b) => b.latest - a.latest)
  }, [allFilings, filings])

  async function patch(id: string, body: Parameters<typeof api.updateOigTip>[1]) {
    await api.updateOigTip(id, body)
    qc.invalidateQueries({ queryKey: ['oig-tips'] })
    qc.invalidateQueries({ queryKey: ['oig-tips-filed'] })
  }

  return (
    <div className="space-y-5">
      <Breadcrumbs />
      <div>
        <h1 className="text-xl font-display font-bold text-ink-primary tracking-tight">Tips &amp; Referrals &mdash; OIG, MFCU &amp; DOJ</h1>
        <p className="text-sm text-ink-tertiary mt-1 max-w-3xl leading-relaxed">
          Everything you've reported, one row per provider: HHS-OIG Hotline tips, state MFCU
          referrals and DOJ Criminal Tip Rewards tips (america.gov/fraud), with each filing's
          lifecycle and outcome.
        </p>
      </div>

      <TipUpdatesCard />

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
            ['all', `All (${allFilings.length})`],
            ['oig', `OIG (${channelCount('oig')})`],
            ['mfcu', `MFCU (${channelCount('mfcu')})`],
            ['doj', `DOJ (${channelCount('doj')})`],
          ] as const).map(([key, label], i) => (
            <button
              key={key}
              onClick={() => setChannel(key)}
              className={`px-3 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors ${i ? 'border-l border-hairline' : ''} ${
                channel === key
                  ? key === 'doj' ? 'bg-amber-400/10 text-amber-300' : key === 'oig' ? 'bg-teal-400/10 text-teal-300'
                    : key === 'mfcu' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-surface-2 text-filament-core'
                  : 'text-ink-tertiary hover:text-ink-secondary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {data && channel !== 'mfcu' && (
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
      {data && allFilings.length === 0 && (
        <div className="card">
          <p className="text-sm text-ink-tertiary">
            No tips logged yet. Open a provider, generate an <span className="text-filament-core">OIG Hotline Tip</span> or
            a <span className="text-amber-300">DOJ Tip</span>, and click “Log as filed” after you submit it.
          </p>
        </div>
      )}

      {data && allFilings.length > 0 && filings.length === 0 && (
        <div className="card"><p className="text-sm text-ink-tertiary">No {channel.toUpperCase()} tips logged yet.</p></div>
      )}

      {filings.length > 0 && (
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
              {groups.map((g) => (
                <tr key={g.npi} className="border-b border-hairline/60 hover:bg-surface-2/40 align-top">
                  <td className="py-2 pr-4">
                    <Link to={`/providers/${g.npi}`} className="text-filament-core hover:underline">{g.name}</Link>
                    <span className="block font-mono text-[11px] text-ink-tertiary">{g.npi}{g.state ? ` · ${g.state}` : ''}</span>
                    {g.rows.filter(f => f.tip?.filed_text).map(f => (
                      <details key={f.id} className="mt-1">
                        <summary className="text-[11px] text-ink-tertiary cursor-pointer hover:text-ink-secondary">
                          Text as filed{g.rows.length > 1 ? ` (${f.channel.toUpperCase()})` : ''}
                        </summary>
                        <pre className="mt-1 max-h-64 max-w-xl overflow-auto whitespace-pre-wrap text-[11px] text-ink-secondary bg-surface-2 border border-hairline rounded p-2">{f.tip!.filed_text}</pre>
                      </details>
                    ))}
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex flex-wrap gap-1">
                      {[...g.channels].sort((a, b) => Number(b === channel) - Number(a === channel)).map(c => (
                        <ChannelBadge key={c} channel={c}
                          dim={channel !== 'all' && channel !== c}
                          title={channel !== 'all' && channel !== c ? `Also filed with ${c.toUpperCase()}` : undefined} />
                      ))}
                    </div>
                  </td>
                  <td className="py-2 pr-4"><Magnitude score={g.risk} size="sm" /></td>
                  <td className="py-2 pr-4 font-mono text-xs text-ink-tertiary">
                    {g.rows.map(f => (
                      <div key={f.id} className="flex items-start gap-1.5 min-h-[30px]">
                        {g.rows.length > 1 && <ChannelBadge channel={f.channel} small />}
                        <span>
                          {f.filed_at ? new Date(f.filed_at * 1000).toLocaleDateString() : '—'}
                          {f.tip?.foia_eligible_at && (
                            <span className="block text-[10px] text-ink-ghost"
                                  title="Earliest date to file a FOIA records request about this complaint">
                              FOIA: {new Date(f.tip.foia_eligible_at * 1000).toLocaleDateString()}
                            </span>
                          )}
                          {f.referral?.jurisdiction && (
                            <span className="block text-[10px] text-ink-ghost">{f.referral.jurisdiction}</span>
                          )}
                        </span>
                      </div>
                    ))}
                  </td>
                  <td className="py-2 pr-4">
                    {g.rows.map(f => (
                      <div key={f.id} className="min-h-[30px]">
                        {f.tip ? (
                          <select
                            value={f.tip.status}
                            onChange={(e) => patch(f.tip!.id, { status: e.target.value as OigTip['status'] })}
                            className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs font-mono text-ink-secondary"
                          >
                            {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                          </select>
                        ) : (
                          <span className="inline-block px-2 py-1 text-xs font-mono text-ink-secondary">
                            {(f.referral?.stage ?? '').replace(/_/g, ' ')}
                          </span>
                        )}
                      </div>
                    ))}
                  </td>
                  <td className="py-2 pr-4">
                    {g.rows.map(f => (
                      <div key={f.id} className="min-h-[30px]">
                        {f.tip ? (
                          <input
                            defaultValue={f.tip.reference_number}
                            onBlur={(e) => { if (e.target.value !== f.tip!.reference_number) patch(f.tip!.id, { reference_number: e.target.value }) }}
                            placeholder="—"
                            className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs font-mono text-ink-secondary w-48"
                          />
                        ) : (
                          <span className="inline-block px-2 py-1 text-xs font-mono text-ink-secondary">
                            {f.referral?.case_number || f.referral?.referral_id}
                          </span>
                        )}
                      </div>
                    ))}
                  </td>
                  <td className="py-2">
                    {g.rows.map(f => (
                      <div key={f.id} className="min-h-[30px]">
                        {f.tip ? (
                          <input
                            defaultValue={f.tip.outcome_notes}
                            onBlur={(e) => { if (e.target.value !== f.tip!.outcome_notes) patch(f.tip!.id, { outcome_notes: e.target.value }) }}
                            placeholder="—"
                            className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs text-ink-secondary w-full min-w-[180px]"
                          />
                        ) : (
                          <Link to={`/providers/${f.npi}/referral`} className="inline-block px-2 py-1 text-xs text-emerald-300 hover:underline">
                            {f.referral?.outcome_notes || 'Open MFCU referral'} &rarr;
                          </Link>
                        )}
                      </div>
                    ))}
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
