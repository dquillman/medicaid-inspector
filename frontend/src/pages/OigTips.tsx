import { Link } from 'react-router-dom'
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

  async function patch(id: string, body: Parameters<typeof api.updateOigTip>[1]) {
    await api.updateOigTip(id, body)
    qc.invalidateQueries({ queryKey: ['oig-tips'] })
    qc.invalidateQueries({ queryKey: ['oig-tips-filed'] })
  }

  return (
    <div className="space-y-5">
      <Breadcrumbs />
      <div>
        <h1 className="text-xl font-display font-bold text-ink-primary tracking-tight">OIG Hotline Tips</h1>
        <p className="text-sm text-ink-tertiary mt-1 max-w-3xl leading-relaxed">
          Every tip you've filed with the HHS-OIG Hotline, its lifecycle, and outcome. Track an
          acknowledgment or action here — an OIG response indicating action is the evidence that
          the detection pipeline is producing real, fileable leads.
        </p>
      </div>

      {data && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
          {STATUSES.map((s) => (
            <div key={s} className="card py-2.5">
              <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.12em]">{s.replace('_', ' ')}</p>
              <p className={`text-lg font-mono tabular-nums ${STATUS_TONE[s]}`}>{data.counts.by_status?.[s] ?? 0}</p>
            </div>
          ))}
        </div>
      )}

      {isLoading && <div className="card h-24 flex items-center justify-center text-ink-tertiary text-sm font-mono">Loading tips…</div>}
      {error != null && <div className="card border-threat-critical/60"><p className="text-sm text-threat-high">Failed to load: {String(error)}</p></div>}
      {data && data.tips.length === 0 && (
        <div className="card">
          <p className="text-sm text-ink-tertiary">
            No tips logged yet. Open a provider, generate an <span className="text-filament-core">OIG Hotline Tip</span>, and click
            “Log as filed” after you submit it at oig.hhs.gov.
          </p>
        </div>
      )}

      {data && data.tips.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] text-ink-tertiary uppercase tracking-[0.14em] border-b border-hairline">
                <th className="py-2 pr-4">Provider</th>
                <th className="py-2 pr-4">Risk</th>
                <th className="py-2 pr-4">Filed</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">OIG Ref #</th>
                <th className="py-2">Outcome notes</th>
              </tr>
            </thead>
            <tbody>
              {data.tips.map((t) => (
                <tr key={t.id} className="border-b border-hairline/60 hover:bg-surface-2/40">
                  <td className="py-2 pr-4">
                    <Link to={`/providers/${t.npi}`} className="text-filament-core hover:underline">{t.provider_name || t.npi}</Link>
                    <span className="block font-mono text-[11px] text-ink-tertiary">{t.npi}{t.state ? ` · ${t.state}` : ''}</span>
                  </td>
                  <td className="py-2 pr-4"><Magnitude score={t.risk_score} size="sm" /></td>
                  <td className="py-2 pr-4 font-mono text-xs text-ink-tertiary">{new Date(t.filed_at * 1000).toLocaleDateString()}</td>
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
                      className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs font-mono text-ink-secondary w-28"
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
