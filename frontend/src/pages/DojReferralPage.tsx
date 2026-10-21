import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import CopyBlock from '../components/CopyBlock'
import FormAnswerSheet from '../components/FormAnswerSheet'

const PORTAL = 'https://america.gov/fraud'
const FIRST_BOX_MAX = 2000

/**
 * DOJ Criminal Tip Rewards Pilot Program — the third referral destination,
 * next to OIG and MFCU. Same ONE generator (`/oig-tip?destination=doj`): the
 * evidence body is identical; only the routing header/footer, the short
 * first-box version and the filing guide differ.
 *
 * The portal (america.gov/fraud) is an AI chat intake, not a fixed wizard:
 * one 2,000-char "What raised your concern?" box, up to 5 attachments (no
 * .html), then follow-up questions, then Submit -> a reference number. So this
 * page gives: the short version for the box, the full narrative as a .txt to
 * attach, the answers for the follow-ups, and a log that records the portal's
 * reference number and sets the case to Reported: DOJ.
 */
export default function DojReferralPage() {
  const { npi } = useParams<{ npi: string }>()
  const queryClient = useQueryClient()

  const [notes, setNotes] = useState('')
  const [refNumber, setRefNumber] = useState('')
  const [logged, setLogged] = useState(false)
  const [logging, setLogging] = useState(false)
  const [logError, setLogError] = useState('')
  const [downloadError, setDownloadError] = useState('')

  const { data: provider } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })
  const providerName = provider?.nppes?.name ?? provider?.provider_name ?? `NPI ${npi}`
  const riskScore = provider?.risk_score ?? 0
  const providerState = provider?.state ?? provider?.nppes?.address?.state ?? ''

  const { data: filed } = useQuery({
    queryKey: ['oig-tips-filed'],
    queryFn: () => api.oigTipsFiled(),
  })
  const alreadyFiled = !!filed?.doj_npis?.includes(npi ?? '')

  const { data: tip, isLoading: tipLoading, error: tipError } = useQuery({
    queryKey: ['referral-narrative', npi, 'doj'],
    queryFn: () => api.oigTip(npi!, 'doj'),
    enabled: !!npi,
    staleTime: 5 * 60_000,
  })
  const fullNarrative = tip?.text ?? ''
  const shortVersion = tip?.short_narrative ?? ''
  const guide = tip?.filing_guide
  const priority = tip?.doj_priority
  const priorFilings = guide?.prior_filings ?? []
  // The first form-field row IS the short version, already shown in its own
  // copy box above — don't show it twice.
  const followUpFields = (tip?.form_fields ?? []).slice(1)

  const handleDownload = () => {
    setDownloadError('')
    try {
      const blob = new Blob([fullNarrative.replace(/\n/g, '\r\n')], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `DOJ-tip-${npi}-full-narrative.txt`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'Download failed')
    }
  }

  const handleLog = async () => {
    if (!window.confirm(
      `Log this as filed with the DOJ Criminal Tip Rewards portal?\n\n` +
      `This app does NOT transmit anything. It records that YOU already submitted ` +
      `this tip at america.gov/fraud, and sets this case to "Reported: DOJ".\n\n` +
      `If you have not actually filed yet, click Cancel, submit there first, ` +
      `then come back and log it with the portal's reference number.`
    )) return
    setLogging(true); setLogError('')
    try {
      await api.logOigTip({
        npi: npi!,
        provider_name: providerName,
        state: providerState,
        risk_score: riskScore,
        notes: notes || undefined,
        destination: 'doj',
        reference_number: refNumber.trim() || undefined,
      })
      setLogged(true)
      queryClient.invalidateQueries({ queryKey: ['oig-tips-filed'] })
      queryClient.invalidateQueries({ queryKey: ['oig-tips'] })
      queryClient.invalidateQueries({ queryKey: ['provider', npi] })
      queryClient.invalidateQueries({ queryKey: ['review'] })
    } catch (err) {
      setLogError(err instanceof Error ? err.message : 'Log failed')
    } finally {
      setLogging(false)
    }
  }

  const inputClass =
    'bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:border-amber-500 focus:outline-none w-full'

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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          {tipLoading && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-8 flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">Drafting the DOJ tip for this provider...</p>
            </div>
          )}
          {tipError != null && (
            <div className="bg-red-950/40 border border-red-800/60 rounded-lg px-4 py-3 text-sm text-red-300">
              Could not draft the tip: {tipError instanceof Error ? tipError.message : String(tipError)}
            </div>
          )}

          {!tipLoading && tip && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6 space-y-5">
              {alreadyFiled && !logged && (
                <div className="bg-amber-950/40 border border-amber-800/50 rounded-lg px-4 py-2.5 text-amber-200 text-xs">
                  A DOJ tip is already logged for this provider. File again only with materially new
                  evidence &mdash; DOJ pays one award per <em>distinct</em> tip.
                </div>
              )}

              <p className="text-[11px] text-gray-400">
                {tip.saved_to_case || tip.save_skipped?.startsWith('an identical')
                  ? 'This draft is saved in the provider’s case notes (Review Queue → open the case → Case notes).'
                  : `Draft not saved to the case: ${tip.save_skipped || 'unknown reason'}`}
              </p>

              {priorFilings.length > 0 && (
                <div className="bg-teal-950/40 border border-teal-800/50 rounded-lg px-4 py-2.5 text-teal-200 text-xs">
                  Already reported:{' '}
                  {priorFilings.map(f => `${f.agency} on ${f.date}`).join(' and ')}. The short version
                  says so. Keep that sentence: DOJ counts you as an original source only if you were the
                  source of the earlier report.
                </div>
              )}

              {/* Destination + reward facts */}
              <div className="bg-amber-950/30 border border-amber-700/50 rounded-lg px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] uppercase tracking-wider text-amber-300/90 font-semibold">
                    Federal destination &mdash; DOJ Criminal Tip Rewards portal
                  </p>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300 border border-emerald-700/50">verified 2026-10-20</span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-xs">
                  <a href={PORTAL} target="_blank" rel="noopener noreferrer" className="text-amber-300 hover:text-amber-200 underline">
                    america.gov/fraud ↗
                  </a>
                  <a href="https://www.justice.gov/fraud/criminal-tip-rewards-pilot-program-faqs" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-gray-200 underline">
                    DOJ program FAQ ↗
                  </a>
                </div>
                <ul className="text-[11px] text-gray-300 mt-2 space-y-0.5 list-disc pl-4">
                  <li>Reward: <span className="font-mono tabular-nums">$10,000&ndash;$30,000</span> per distinct tip, at DOJ&rsquo;s discretion &mdash; only if the tip leads to unsealed criminal charges.</li>
                  <li>Give your real contact info in the portal. It is required for a reward (anonymous only through an attorney).</li>
                  <li>This app never transmits anything. You file at the portal, then log it here.</li>
                </ul>
              </div>

              {/* Filing guide */}
              {guide && (
                <div className="border border-gray-700 rounded-lg overflow-hidden">
                  <div className="px-4 py-2.5 border-b border-gray-700 bg-gray-900/40">
                    <h3 className="text-sm font-bold text-gray-200">Filing guide &mdash; step by step</h3>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      Derived for THIS provider. The portal is an AI chat, so its follow-up questions can
                      vary &mdash; answer from these lines and never guess.
                    </p>
                  </div>
                  <ol className="divide-y divide-gray-800">
                    {guide.steps.map(([q, a], i) => (
                      <li key={i} className="px-4 py-2 text-xs">
                        <div className="flex gap-3">
                          <span className="text-gray-500 shrink-0 w-6 font-mono tabular-nums">{i + 1}.</span>
                          <div className="flex-1">
                            <p className="text-gray-300 font-medium">{q}</p>
                            <p className="text-amber-300 mt-0.5">{a}</p>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                  {guide.notes.length > 0 && (
                    <div className="px-4 py-2.5 border-t border-gray-800 bg-gray-900/20">
                      <ul className="space-y-1">
                        {guide.notes.map((n, i) => (
                          <li key={i} className="text-[11px] text-gray-400">&bull; {n}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Step 2: the first box */}
              {shortVersion && (
                <div>
                  <CopyBlock
                    text={shortVersion}
                    tone="primary"
                    rows={9}
                    buttonLabel="Copy short version"
                    title={<>Paste this first &mdash; &ldquo;What raised your concern?&rdquo;</>}
                    subtitle={
                      <>
                        <span className={`font-mono tabular-nums ${shortVersion.length > FIRST_BOX_MAX ? 'text-red-400' : ''}`}>
                          {shortVersion.length.toLocaleString()}
                        </span>
                        {' '}of {FIRST_BOX_MAX.toLocaleString()} characters the portal box allows.
                      </>
                    }
                  />
                </div>
              )}

              {/* Step 3: attach the full narrative */}
              {fullNarrative && (
                <div className="border border-gray-700 rounded-lg px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-200">Attach the full narrative</h3>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      The portal takes up to 5 files (.txt, .pdf, .docx, .csv, &hellip; &mdash; NOT .html).
                      Download this .txt and attach it with &ldquo;Add supporting documents&rdquo;.
                    </p>
                    {downloadError && <p className="text-[11px] text-red-400 mt-1">{downloadError}</p>}
                  </div>
                  <button
                    type="button"
                    onClick={handleDownload}
                    className="shrink-0 px-3 py-1.5 text-xs font-semibold bg-amber-600 hover:bg-amber-500 text-black rounded transition-colors"
                  >
                    Download full narrative (.txt)
                  </button>
                </div>
              )}

              {fullNarrative && (
                <CopyBlock
                  text={fullNarrative}
                  tone="secondary"
                  rows={12}
                  buttonLabel="Copy full narrative"
                  title={<>Full narrative (the evidence)</>}
                  subtitle={<>The same text as the .txt above. Paste it in if the portal asks for more detail.</>}
                />
              )}

              {/* Step 4: follow-up answers */}
              {followUpFields.length > 0 && (
                <div className="mt-1">
                  <h3 className="text-sm font-semibold text-gray-200 mb-2">
                    Answers for the portal&rsquo;s follow-up questions
                  </h3>
                  <FormAnswerSheet fields={followUpFields} formName="the DOJ portal" />
                </div>
              )}

              {/* Case record */}
              <div className="mt-2 mb-2 border-t border-gray-800 pt-4">
                <h3 className="text-sm font-semibold text-gray-200">Your case record</h3>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  Stays in this app. Nothing here is sent to DOJ &mdash; it records what <em>you</em> filed,
                  so the Review Queue shows Reported: DOJ.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-gray-300 text-xs font-medium mb-1">
                    Portal reference number <span className="text-gray-600">(shown after Submit)</span>
                  </label>
                  <input
                    className={`${inputClass} font-mono`}
                    value={refNumber}
                    onChange={e => setRefNumber(e.target.value)}
                    placeholder="Paste the portal's reference number"
                  />
                </div>
                <div>
                  <label className="block text-gray-300 text-xs font-medium mb-1">
                    Notes <span className="text-gray-600">(optional)</span>
                  </label>
                  <input
                    className={inputClass}
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="Your own notes (kept in the app)"
                  />
                </div>
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
                  title="Records that YOU already filed at america.gov/fraud and marks the case Reported: DOJ. This app never transmits to DOJ."
                >
                  {logged ? 'Logged ✓' : logging ? 'Logging…' : 'Log DOJ Tip as Filed'}
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
              <Link to={`/providers/${npi}/oig-referral`} className="block text-xs text-blue-400 hover:text-blue-300">OIG Hotline tip &rarr;</Link>
              <Link to={`/providers/${npi}/referral`} className="block text-xs text-blue-400 hover:text-blue-300">State MFCU referral &rarr;</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
