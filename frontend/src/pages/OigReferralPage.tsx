import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'

/**
 * Dedicated OIG Hotline referral page — the federal counterpart to
 * MFCUReferralPage. Previously "OIG Hotline Tip" opened a modal that showed
 * only the plain narrative; the per-provider filing guide the backend has
 * generated since v3.33.0 (`filing_guide` / `text_with_guide`) was never
 * rendered anywhere in the app. This page fixes that and brings OIG to
 * parity with the MFCU flow: filing guide, full narrative, short version,
 * and a case record that's the SAME action as marking the case Reported: OIG
 * (see routes/oig_tips.py — POST /api/oig-tips now flips queue_status).
 */
export default function OigReferralPage() {
  const { npi } = useParams<{ npi: string }>()
  const queryClient = useQueryClient()

  const [narrativeCopied, setNarrativeCopied] = useState(false)
  const [shortCopied, setShortCopied] = useState(false)
  const [notes, setNotes] = useState('')
  const [logged, setLogged] = useState(false)
  const [logging, setLogging] = useState(false)
  const [logError, setLogError] = useState('')

  const { data: provider } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })
  const providerName = provider?.nppes?.name ?? provider?.provider_name ?? `NPI ${npi}`
  const riskScore = provider?.risk_score ?? 0
  const flaggedSignals = (provider?.signal_results ?? []).filter(s => s.flagged)
  const providerState = provider?.state ?? provider?.nppes?.address?.state ?? ''

  const { data: filedNpis } = useQuery({
    queryKey: ['oig-tips-filed'],
    queryFn: () => api.oigTipsFiled(),
  })
  const alreadyFiled = !!filedNpis?.npis.includes(npi ?? '')

  const { data: tip, isLoading: tipLoading } = useQuery({
    queryKey: ['referral-narrative', npi, 'oig'],
    queryFn: () => api.oigTip(npi!, 'oig'),
    enabled: !!npi,
    staleTime: 5 * 60_000,
  })
  const autoNarrative = tip?.text ?? ''
  const shortNarrative = tip?.short_narrative ?? ''
  const guide = tip?.filing_guide

  const handleLog = async () => {
    if (!window.confirm(
      `Log this as filed with the HHS-OIG Hotline?

` +
      `This app does NOT transmit anything. It records that YOU already submitted ` +
      `this tip at tips.oig.hhs.gov, and sets this case to "Reported: OIG".

` +
      `If you have not actually filed yet, click Cancel, submit there first, ` +
      `then come back and log it.`
    )) return
    setLogging(true); setLogError('')
    try {
      await api.logOigTip({
        npi: npi!,
        provider_name: providerName,
        state: providerState,
        risk_score: riskScore,
        notes: notes || undefined,
      })
      setLogged(true)
      queryClient.invalidateQueries({ queryKey: ['oig-tips-filed'] })
      queryClient.invalidateQueries({ queryKey: ['provider', npi] })
    } catch (err) {
      setLogError(err instanceof Error ? err.message : 'Log failed')
    } finally {
      setLogging(false)
    }
  }

  const inputClass =
    'bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none w-full'

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/providers" className="hover:text-gray-300">Providers</Link>
        <span>/</span>
        <Link to={`/providers/${npi}`} className="hover:text-gray-300 font-mono">{npi}</Link>
        <span>/</span>
        <span className="text-gray-300">OIG Hotline Tip</span>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-white font-bold text-xl">OIG Hotline Tip</h1>
          <p className="text-gray-400 text-sm mt-0.5">{providerName}</p>
        </div>
        <Link to={`/providers/${npi}`} className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1">
          &larr; Back to Provider
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          {tipLoading && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-8 flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">Drafting the tip for this provider...</p>
            </div>
          )}

          {!tipLoading && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6 space-y-5">
              {alreadyFiled && !logged && (
                <div className="bg-blue-950/40 border border-blue-800/50 rounded-lg px-4 py-2.5 text-blue-300 text-xs">
                  An OIG tip is already logged for this provider. Filing again is fine if this is a
                  follow-up or new evidence.
                </div>
              )}

              {/* Federal destination — one hotline, no per-state lookup */}
              <div className="bg-blue-950/40 border border-blue-800/50 rounded-lg px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] uppercase tracking-wider text-blue-300/80 font-semibold">
                    Federal destination — HHS-OIG Hotline
                  </p>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300 border border-emerald-700/50">verified</span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-xs">
                  <a href="https://tips.oig.hhs.gov/" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline">
                    tips.oig.hhs.gov ↗
                  </a>
                  <span className="text-gray-400">1-800-HHS-TIPS</span>
                </div>
                <p className="text-[11px] text-amber-200/90 mt-2 font-medium">
                  Three steps: (1) Use the filing guide below to answer each wizard screen. (2) COPY
                  the narrative and paste it into the wizard&rsquo;s description field &mdash; this
                  app never transmits anything. (3) Come back and log it so your case record matches
                  what you actually filed.
                </p>
              </div>

              {/* THE FILING GUIDE — per-provider wizard answer sheet. This is
                  the piece that shipped on the backend in v3.33.0 but was
                  never rendered anywhere until this page. */}
              {guide && (
                <div className="border border-gray-700 rounded-lg overflow-hidden">
                  <div className="px-4 py-2.5 border-b border-gray-700 bg-gray-900/40">
                    <h3 className="text-sm font-bold text-gray-200">
                      Filing guide &mdash; what to pick on each screen
                    </h3>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      Derived for THIS provider. Answers differ by provider (taxonomy, which
                      signals fired, entity type) &mdash; never assume last provider&rsquo;s answers apply.
                    </p>
                  </div>
                  <div className="divide-y divide-gray-800">
                    {guide.steps.map(([q, a], i) => (
                      <div key={i} className="flex items-start gap-3 px-4 py-2 text-xs">
                        <span className="text-gray-500 shrink-0 w-6">{i + 1}.</span>
                        <span className="text-gray-400 flex-1">{q}</span>
                        <span className="text-amber-300 font-semibold text-right shrink-0 max-w-[45%]">{a}</span>
                      </div>
                    ))}
                  </div>
                  {guide.notes.length > 0 && (
                    <div className="px-4 py-2.5 border-t border-gray-800 bg-gray-900/20">
                      <ul className="space-y-1">
                        {guide.notes.map((n, i) => (
                          <li key={i} className="text-[11px] text-gray-500">&bull; {n}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* THE SUBMISSION */}
              {autoNarrative && (
                <div className="border-2 border-amber-500/60 rounded-lg bg-amber-950/20">
                  <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-amber-500/30">
                    <div>
                      <h3 className="text-sm font-bold text-amber-300">
                        Copy this. It is what you submit.
                      </h3>
                      <p className="text-[11px] text-amber-200/70 mt-0.5">
                        Paste into the wizard&rsquo;s &ldquo;describe the fraudulent action&rdquo; field.
                        This app does not send it.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        navigator.clipboard?.writeText(autoNarrative)
                        setNarrativeCopied(true)
                        setTimeout(() => setNarrativeCopied(false), 2000)
                      }}
                      className="shrink-0 px-3 py-1.5 text-xs font-semibold bg-amber-600 hover:bg-amber-500 text-black rounded transition-colors"
                    >
                      {narrativeCopied ? 'Copied ✓' : 'Copy narrative'}
                    </button>
                  </div>
                  <pre className="max-h-72 overflow-auto px-4 py-3 text-[11px] font-mono text-gray-300 whitespace-pre-wrap">
                    {autoNarrative}
                  </pre>
                </div>
              )}

              {shortNarrative && (
                <div className="border border-amber-500/30 rounded-lg bg-amber-950/10">
                  <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-amber-500/20">
                    <div>
                      <h3 className="text-xs font-bold text-amber-300/90">
                        Short version — for a small description field
                      </h3>
                      <p className="text-[11px] text-amber-200/60 mt-0.5">
                        Same facts, condensed. OIG&rsquo;s box is usually large enough for the full
                        narrative above, but use this if space is tight.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        navigator.clipboard?.writeText(shortNarrative)
                        setShortCopied(true)
                        setTimeout(() => setShortCopied(false), 2000)
                      }}
                      className="shrink-0 px-3 py-1.5 text-xs font-semibold bg-amber-700/70 hover:bg-amber-600 text-black rounded transition-colors"
                    >
                      {shortCopied ? 'Copied ✓' : 'Copy short version'}
                    </button>
                  </div>
                  <p className="px-4 py-3 text-[11px] font-mono text-gray-300 whitespace-pre-wrap">
                    {shortNarrative}
                  </p>
                </div>
              )}

              {/* Case record — stays in the app. Logging IS marking Reported: OIG. */}
              <div className="mt-2 mb-2 border-t border-gray-800 pt-4">
                <h3 className="text-sm font-semibold text-gray-200">Your case record</h3>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  Stays in this app. Nothing here is sent to OIG &mdash; it records what{' '}
                  <em>you</em> filed, so the Review Queue matches reality.
                </p>
              </div>
              <div>
                <label className="block text-gray-300 text-xs font-medium mb-1">
                  Notes <span className="text-gray-600">(optional)</span>
                </label>
                <textarea
                  className={`${inputClass} min-h-[70px] resize-y`}
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  placeholder="Your own notes about this tip (kept in the app)"
                  rows={3}
                />
              </div>

              {logError && <p className="text-xs text-red-400">{logError}</p>}

              <div className="flex items-center justify-end gap-3 pt-2">
                <Link to={`/providers/${npi}`} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors">
                  {logged ? 'Done — Back to Provider' : 'Cancel'}
                </Link>
                <button
                  onClick={handleLog}
                  disabled={logging || logged}
                  className="bg-amber-600 hover:bg-amber-500 disabled:opacity-60 text-black font-bold px-6 py-2.5 rounded transition-colors"
                  title="Records that YOU already filed at tips.oig.hhs.gov and marks the case Reported: OIG. This app never transmits to OIG."
                >
                  {logged ? 'Logged ✓' : logging ? 'Logging…' : 'Log OIG Tip as Filed'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-5 sticky top-20">
            <h3 className="text-gray-300 text-xs font-semibold uppercase tracking-wider mb-3">Provider Summary</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Risk Score</span>
                <span className={`text-sm font-bold font-mono px-2 py-0.5 rounded ${
                  riskScore >= 75 ? 'bg-red-900 text-red-300' :
                  riskScore >= 50 ? 'bg-orange-900 text-orange-300' :
                  riskScore >= 25 ? 'bg-yellow-900/50 text-yellow-300' :
                  'bg-green-900/50 text-green-300'
                }`}>
                  {riskScore}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Total Paid</span>
                <span className="text-white text-sm font-mono">{fmt(provider?.spending?.total_paid ?? 0)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Total Claims</span>
                <span className="text-white text-sm font-mono">{(provider?.spending?.total_claims ?? 0).toLocaleString()}</span>
              </div>
            </div>
            {flaggedSignals.length > 0 && (
              <div className="mt-4 pt-3 border-t border-gray-700">
                <p className="text-gray-500 text-xs mb-2">{flaggedSignals.length} Flagged Signals</p>
                <div className="space-y-1">
                  {flaggedSignals.slice(0, 8).map(s => (
                    <div key={s.signal} className="flex items-center justify-between text-xs">
                      <span className="text-red-400 truncate max-w-[140px]" title={s.signal}>
                        {s.signal.replace(/_/g, ' ')}
                      </span>
                      <span className="text-gray-500 font-mono">{s.score.toFixed(0)}</span>
                    </div>
                  ))}
                  {flaggedSignals.length > 8 && (
                    <p className="text-gray-600 text-xs">+{flaggedSignals.length - 8} more</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
