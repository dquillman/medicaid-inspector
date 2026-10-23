import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import CopyBlock from './CopyBlock'
import type { TipSupplement } from '../lib/types'

/**
 * Filed tips that left out the per-se key finding (revoked / terminated /
 * dead NPI). Before v3.61.3 the generator never read the per-se sweep, so the
 * agency got the statistics but not the fact that makes the lead provable.
 * Each row has a short update note to send as a follow-up. Hidden when there
 * is nothing to send.
 */
export default function TipUpdatesCard() {
  const { data } = useQuery({
    queryKey: ['tip-supplements'],
    queryFn: () => api.tipSupplements(),
    staleTime: 60_000,
  })
  const [open, setOpen] = useState<string | null>(null)

  if (!data || (data.items.length === 0 && data.skipped.length === 0)) return null
  const total = data.items.reduce((s, i) => s + (i.amount ?? 0), 0)

  return (
    <div className="card border-amber-400/40 bg-amber-400/5 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-amber-300">
          {data.items.length} filed tip{data.items.length === 1 ? '' : 's'} left out the key finding
        </h2>
        <p className="text-xs text-ink-secondary mt-1 leading-relaxed max-w-3xl">
          These tips went in before the report started with the provider&rsquo;s bar (Medicare
          revocation, state termination or dead NPI). The agency got the statistics but not the
          fact that makes the lead provable, or the{' '}
          <span className="font-mono">${Math.round(total).toLocaleString()}</span> paid while barred.
          Send each one a short update. Do not refile the whole tip.
        </p>
        <p className="text-[11px] text-ink-tertiary mt-1.5 leading-relaxed max-w-3xl">
          <span className="text-amber-300">DOJ:</span> start a new report at america.gov/fraud, paste
          the update as the first box, and say it adds to your earlier reference number.{' '}
          <span className="text-teal-300">OIG:</span> file a new Hotline complaint with the update.
        </p>
      </div>

      <div className="divide-y divide-hairline border border-hairline rounded">
        {data.items.map(item => (
          <UpdateRow key={item.tip_id} item={item}
            open={open === item.tip_id}
            onToggle={() => setOpen(open === item.tip_id ? null : item.tip_id)} />
        ))}
      </div>

      {data.skipped.length > 0 && (
        <p className="text-[11px] text-ink-tertiary">
          No update recommended:{' '}
          {data.skipped.map((s, i) => (
            <span key={s.tip_id}>{i ? '; ' : ''}{s.provider_name} &mdash; {s.reason}</span>
          ))}
        </p>
      )}
    </div>
  )
}

function UpdateRow({ item, open, onToggle }: { item: TipSupplement; open: boolean; onToggle: () => void }) {
  const qc = useQueryClient()
  const [ref, setRef] = useState('')
  const [state, setState] = useState<'idle' | 'saving' | 'failed'>('idle')

  async function logSent() {
    setState('saving')
    try {
      await api.logTipSupplement(item.tip_id, { text: item.text ?? '', reference_number: ref })
      qc.invalidateQueries({ queryKey: ['tip-supplements'] })
      qc.invalidateQueries({ queryKey: ['oig-tips'] })
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="px-3 py-2">
      <button onClick={onToggle} className="w-full flex items-center gap-3 text-left">
        <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border ${
          item.destination === 'doj' ? 'text-amber-300 border-amber-400/40' : 'text-teal-300 border-teal-400/40'}`}>
          {item.destination}
        </span>
        <span className="text-sm text-ink-primary flex-1 truncate">{item.provider_name}</span>
        <span className="text-xs font-mono text-ink-secondary tabular-nums">
          ${Math.round(item.amount ?? 0).toLocaleString()}
        </span>
        <span className="text-[11px] text-ink-tertiary hidden sm:inline">
          filed {new Date(item.filed_at * 1000).toLocaleDateString()}
        </span>
        <span className="text-[11px] text-filament-core">{open ? 'Hide' : 'Show update'}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <p className="text-[11px] text-ink-tertiary">
            {item.coverage === 'missing'
              ? 'Checked: the text you filed does not say this.'
              : 'The filed text was not saved. It went in before the fix, so it almost surely left this out.'}
            {' '}<Link to={`/providers/${item.npi}`} className="text-filament-core hover:underline">Open provider</Link>
          </p>
          <CopyBlock text={item.text ?? ''} rows={12} buttonLabel="Copy update"
            title={<>Update for {item.reference_number}</>} />
          <div className="flex flex-wrap items-center gap-2">
            <input value={ref} onChange={e => setRef(e.target.value)}
              placeholder={item.destination === 'doj' ? 'New TFF reference (optional)' : 'Reference (optional)'}
              className="bg-surface-2 border border-hairline rounded px-2 py-1 text-xs font-mono text-ink-secondary w-64" />
            <button onClick={logSent} disabled={state === 'saving'}
              className="px-3 py-1.5 rounded bg-amber-500 text-black text-xs font-semibold hover:bg-amber-400 disabled:opacity-50">
              {state === 'saving' ? 'Saving…' : 'Log update as sent'}
            </button>
            {state === 'failed' && <span className="text-xs text-threat-high">Save failed. Try again.</span>}
            <span className="text-[11px] text-ink-tertiary">Saved on the tip record. The first tip&rsquo;s text stays as filed.</span>
          </div>
        </div>
      )}
    </div>
  )
}
