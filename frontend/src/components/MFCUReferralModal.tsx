import { useState, useEffect, useCallback, useRef } from 'react'
import { get, mutate } from '../lib/api'
import type { MFCUReferral } from '../lib/types'

/* ─── Props ─────────────────────────────────────────────────────────────── */

interface FlaggedSignal {
  signal: string
  flagged: boolean
  score: number
  reason: string
}

interface MFCUReferralModalProps {
  npi: string
  providerName: string
  riskScore: number
  flaggedSignals: FlaggedSignal[]
  onClose: () => void
  onSuccess: () => void
}

/* ─── Gate types ────────────────────────────────────────────────────────── */

interface GateResult {
  label: string
  passed: boolean
  detail: string
}

type Phase = 'gate-loading' | 'gate-result' | 'form' | 'submitting' | 'success' | 'error'

/* ─── Component ─────────────────────────────────────────────────────────── */

export default function MFCUReferralModal({
  npi,
  providerName,
  riskScore,
  flaggedSignals,
  onClose,
  onSuccess,
}: MFCUReferralModalProps) {
  const [phase, setPhase] = useState<Phase>('gate-loading')
  const [gates, setGates] = useState<GateResult[]>([])
  const [overridden, setOverridden] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [referralId, setReferralId] = useState<string | null>(null)

  // Form fields
  const [jurisdiction, setJurisdiction] = useState('')
  const [mfcuContact, setMfcuContact] = useState('')
  const [caseNumber, setCaseNumber] = useState('')
  const [notes, setNotes] = useState('')

  const backdropRef = useRef<HTMLDivElement>(null)

  /* ── Close on Escape ──────────────────────────────────────────────────── */

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  /* ── Gate check on mount ──────────────────────────────────────────────── */

  useEffect(() => {
    let cancelled = false

    async function runGateCheck() {
      try {
        const [oig, sam, refs] = await Promise.all([
          get<{ excluded: boolean }>(`/providers/${npi}/oig`),
          get<{ excluded: boolean }>(`/providers/${npi}/sam-exclusion`),
          get<{ referrals: any[]; total: number }>(`/referrals/provider/${npi}`),
        ])

        if (cancelled) return

        const flaggedCount = flaggedSignals.filter(s => s.flagged).length

        // Gate 1: Risk score >= 60
        const gate1: GateResult = {
          label: 'Risk Score Threshold',
          passed: riskScore >= 60,
          detail: riskScore >= 60
            ? `Risk score is ${riskScore} (minimum 60)`
            : `Risk score is ${riskScore} — must be 60 or above`,
        }

        // Gate 2: 3+ HIGH severity signals OR OIG excluded OR SAM excluded
        const gate2Passed = flaggedCount >= 3 || oig.excluded || sam.excluded
        const gate2Parts: string[] = []
        if (flaggedCount >= 3) gate2Parts.push(`${flaggedCount} flagged signals`)
        if (oig.excluded) gate2Parts.push('OIG excluded')
        if (sam.excluded) gate2Parts.push('SAM excluded')
        const gate2: GateResult = {
          label: 'Severity Qualification',
          passed: gate2Passed,
          detail: gate2Passed
            ? gate2Parts.join(', ')
            : `Only ${flaggedCount} flagged signal${flaggedCount === 1 ? '' : 's'} (need 3+), not OIG/SAM excluded`,
        }

        // Gate 3: Evidence present (at least 1 flagged signal)
        const gate3: GateResult = {
          label: 'Evidence Present',
          passed: flaggedCount >= 1,
          detail: flaggedCount >= 1
            ? `${flaggedCount} flagged signal${flaggedCount === 1 ? '' : 's'} available as evidence`
            : 'No flagged signals — no evidence to support referral',
        }

        // Gate 4: No recent referral (submitted or under_investigation in last 90 days)
        const now = Date.now() / 1000 // unix seconds
        const ninetyDaysAgo = now - 90 * 24 * 60 * 60
        const recentActive = (refs.referrals ?? []).filter(
          (r: any) =>
            (r.stage === 'submitted' || r.stage === 'under_investigation') &&
            r.referral_date > ninetyDaysAgo
        )
        const gate4: GateResult = {
          label: 'No Recent Referral',
          passed: recentActive.length === 0,
          detail:
            recentActive.length === 0
              ? 'No active referral in the last 90 days'
              : `${recentActive.length} active referral${recentActive.length === 1 ? '' : 's'} found within last 90 days`,
        }

        setGates([gate1, gate2, gate3, gate4])
        setPhase('gate-result')
      } catch (err: any) {
        if (!cancelled) {
          setErrorMsg(err?.message || 'Failed to run eligibility check')
          setPhase('error')
        }
      }
    }

    runGateCheck()
    return () => { cancelled = true }
  }, [npi, riskScore, flaggedSignals])

  /* ── Helpers ──────────────────────────────────────────────────────────── */

  const allGatesPass = gates.length > 0 && gates.every(g => g.passed)
  const passedCount = gates.filter(g => g.passed).length

  const handleProceed = useCallback(() => {
    setPhase('form')
  }, [])

  const handleOverride = useCallback(() => {
    setOverridden(true)
    setPhase('form')
  }, [])

  const handleSubmit = useCallback(async () => {
    setPhase('submitting')
    try {
      const result = await mutate<MFCUReferral>('POST', `/referrals/${npi}/submit`, {
        jurisdiction: jurisdiction || undefined,
        mfcu_contact: mfcuContact || undefined,
        case_number: caseNumber || undefined,
        notes: notes || undefined,
      })
      setReferralId(result.referral_id ?? String(result.id))
      setPhase('success')
      setTimeout(() => onSuccess(), 2000)
    } catch (err: any) {
      setErrorMsg(err?.message || 'Submission failed')
      setPhase('error')
    }
  }, [npi, jurisdiction, mfcuContact, caseNumber, notes, onSuccess])

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === backdropRef.current) onClose()
    },
    [onClose]
  )

  /* ── Input class ──────────────────────────────────────────────────────── */

  const inputClass =
    'bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none w-full'

  /* ── Render ───────────────────────────────────────────────────────────── */

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 bg-black/60 z-50 flex justify-center overflow-y-auto"
      onClick={handleBackdropClick}
    >
      <div className="max-w-2xl w-full mx-auto mt-16 mb-8 max-h-[80vh] overflow-y-auto bg-gray-900 border border-gray-700 rounded-xl shadow-2xl self-start">
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h2 className="text-white font-bold text-lg tracking-wide">
              MFCU Referral &mdash; NPI {npi}
            </h2>
            <p className="text-gray-400 text-sm mt-0.5">{providerName}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2 transition-colors"
            aria-label="Close"
          >
            &#x2715;
          </button>
        </div>

        <div className="p-6 space-y-5">
          {/* ── Phase: Gate Loading ───────────────────────────────────── */}
          {phase === 'gate-loading' && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">Running eligibility checks...</p>
            </div>
          )}

          {/* ── Phase: Gate Results ───────────────────────────────────── */}
          {phase === 'gate-result' && (
            <>
              <div className="space-y-3">
                {gates.map((gate, i) => (
                  <div
                    key={i}
                    className={`flex items-start gap-3 p-3 rounded-lg border ${
                      gate.passed
                        ? 'bg-green-950/30 border-green-800/40'
                        : 'bg-red-950/30 border-red-800/40'
                    }`}
                  >
                    <span className="text-lg leading-none mt-0.5 flex-shrink-0">
                      {gate.passed ? (
                        <span className="text-green-400">&#x2705;</span>
                      ) : (
                        <span className="text-red-400">&#x274C;</span>
                      )}
                    </span>
                    <div className="min-w-0">
                      <p
                        className={`text-sm font-medium ${
                          gate.passed ? 'text-green-300' : 'text-red-300'
                        }`}
                      >
                        {gate.label}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">{gate.detail}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Summary bar */}
              <div
                className={`text-center py-3 rounded-lg text-sm font-semibold ${
                  allGatesPass
                    ? 'bg-green-900/40 border border-green-700/50 text-green-300'
                    : 'bg-red-900/40 border border-red-700/50 text-red-300'
                }`}
              >
                {allGatesPass ? (
                  <>ELIGIBLE FOR REFERRAL &mdash; {passedCount} of 4 gates passed</>
                ) : (
                  <>NOT ELIGIBLE &mdash; {passedCount} of 4 gates passed</>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Cancel
                </button>
                {allGatesPass ? (
                  <button
                    onClick={handleProceed}
                    className="bg-red-700 hover:bg-red-600 text-white font-bold px-6 py-2.5 rounded transition-colors"
                  >
                    Proceed
                  </button>
                ) : (
                  <button
                    onClick={handleOverride}
                    className="bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm px-5 py-2 rounded border border-gray-600 transition-colors"
                    title="Supervisor override — proceed despite failing gates"
                  >
                    Override &amp; Proceed
                  </button>
                )}
              </div>
            </>
          )}

          {/* ── Phase: Referral Form ─────────────────────────────────── */}
          {phase === 'form' && (
            <>
              {overridden && (
                <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg px-4 py-2.5 text-yellow-300 text-xs">
                  Supervisor override active &mdash; gate requirements were bypassed.
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="block text-gray-300 text-xs font-medium mb-1">
                    Jurisdiction
                  </label>
                  <input
                    type="text"
                    className={inputClass}
                    value={jurisdiction}
                    onChange={e => setJurisdiction(e.target.value)}
                    placeholder="e.g. Florida, TX, New York"
                  />
                </div>

                <div>
                  <label className="block text-gray-300 text-xs font-medium mb-1">
                    MFCU Contact <span className="text-gray-600">(optional)</span>
                  </label>
                  <input
                    type="text"
                    className={inputClass}
                    value={mfcuContact}
                    onChange={e => setMfcuContact(e.target.value)}
                    placeholder="Name or email of MFCU contact"
                  />
                </div>

                <div>
                  <label className="block text-gray-300 text-xs font-medium mb-1">
                    Case Number <span className="text-gray-600">(optional)</span>
                  </label>
                  <input
                    type="text"
                    className={inputClass}
                    value={caseNumber}
                    onChange={e => setCaseNumber(e.target.value)}
                    placeholder="External case or tracking number"
                  />
                </div>

                <div>
                  <label className="block text-gray-300 text-xs font-medium mb-1">
                    Notes <span className="text-gray-600">(optional)</span>
                  </label>
                  <textarea
                    className={`${inputClass} min-h-[80px] resize-y`}
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="Additional context for the MFCU referral..."
                    rows={3}
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  className="bg-red-700 hover:bg-red-600 text-white font-bold px-6 py-2.5 rounded transition-colors"
                >
                  Submit Referral
                </button>
              </div>
            </>
          )}

          {/* ── Phase: Submitting ────────────────────────────────────── */}
          {phase === 'submitting' && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div className="w-8 h-8 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">Submitting referral to MFCU...</p>
            </div>
          )}

          {/* ── Phase: Success ───────────────────────────────────────── */}
          {phase === 'success' && (
            <div className="flex flex-col items-center justify-center py-12 gap-4">
              <div className="w-14 h-14 rounded-full bg-green-900/40 border border-green-700/50 flex items-center justify-center">
                <span className="text-green-400 text-3xl">&#x2713;</span>
              </div>
              <div className="text-center">
                <p className="text-green-300 font-semibold text-lg">
                  Referral Submitted
                </p>
                <p className="text-gray-400 text-sm mt-1">
                  Referral ID: <span className="text-white font-mono">{referralId}</span>
                </p>
              </div>
            </div>
          )}

          {/* ── Phase: Error ─────────────────────────────────────────── */}
          {phase === 'error' && (
            <div className="flex flex-col items-center justify-center py-10 gap-4">
              <div className="w-14 h-14 rounded-full bg-red-900/40 border border-red-700/50 flex items-center justify-center">
                <span className="text-red-400 text-3xl">!</span>
              </div>
              <div className="text-center">
                <p className="text-red-300 font-semibold">Referral Failed</p>
                <p className="text-gray-400 text-sm mt-1">{errorMsg}</p>
              </div>
              <button
                onClick={onClose}
                className="mt-2 px-4 py-2 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 rounded transition-colors"
              >
                Close
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
