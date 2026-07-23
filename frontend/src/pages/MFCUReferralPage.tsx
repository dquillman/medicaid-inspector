import { useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, get, mutate } from '../lib/api'
import { fmt } from '../lib/format'
import type { MFCUReferral } from '../lib/types'
import { useProviderFlags } from '../hooks/useProviderFlags'

// Referral-eligibility threshold, on the FRAUD BRAIN score (the app's authority),
// not the raw 18-signal risk. Calibrated to the real board distribution: the top
// of a 95k-provider board is ~49 and NOTHING scores ≥50, so the legacy raw-risk
// ≥60 gate passed literally no one. 40 captures the genuinely-elevated tier
// (~top-20). Falls back to the raw risk score when the provider isn't on the
// current board (e.g. already Reported → excluded from the Brain ranking).
const BRAIN_REFERRAL_MIN = 40

/* ─── Gate types ────────────────────────────────────────────────────────── */

interface GateResult {
  label: string
  passed: boolean
  detail: string
}

type Phase = 'gate-loading' | 'gate-result' | 'form' | 'submitting' | 'success' | 'error'

/* ─── Component ─────────────────────────────────────────────────────────── */

export default function MFCUReferralPage() {
  const { npi } = useParams<{ npi: string }>()
  const queryClient = useQueryClient()

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

  // ── Provider detail (for header + signal data) ──────────────────────
  const { data: provider } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })

  const providerName = provider?.nppes?.name ?? provider?.provider_name ?? `NPI ${npi}`
  const riskScore = provider?.risk_score ?? 0
  const flaggedSignals = (provider?.signal_results ?? []).filter(s => s.flagged)

  // Brain score is the app's authority. It's undefined for providers not on the
  // current board (off-board or Reported→excluded), so fall back to raw risk.
  const { brainScore } = useProviderFlags()
  const brainVal = brainScore(npi ?? '')
  const usingBrain = brainVal != null
  const eligibilityScore = brainVal ?? riskScore

  // ── Gate check queries ──────────────────────────────────────────────
  const { data: oigData } = useQuery({
    queryKey: ['oig', npi],
    queryFn: () => get<{ excluded: boolean }>(`/providers/${npi}/oig`),
    enabled: !!npi,
  })

  const { data: samData } = useQuery({
    queryKey: ['sam-exclusion', npi],
    queryFn: () => get<{ excluded: boolean }>(`/providers/${npi}/sam-exclusion`),
    enabled: !!npi,
  })

  const { data: refsData } = useQuery({
    queryKey: ['referrals', npi],
    queryFn: () => get<{ referrals: any[]; total: number }>(`/referrals/provider/${npi}`),
    enabled: !!npi,
  })

  // ── Compute gates once all data arrives ─────────────────────────────
  const allLoaded = !!provider && !!oigData && !!samData && !!refsData
  if (allLoaded && phase === 'gate-loading' && gates.length === 0) {
    const flaggedCount = flaggedSignals.length

    const scoreLabel = usingBrain ? 'Brain score' : 'Risk score (off board)'
    const gate1: GateResult = {
      label: 'Fraud Brain Threshold',
      passed: eligibilityScore >= BRAIN_REFERRAL_MIN,
      detail: eligibilityScore >= BRAIN_REFERRAL_MIN
        ? `${scoreLabel} ${eligibilityScore.toFixed(1)} (minimum ${BRAIN_REFERRAL_MIN})`
        : `${scoreLabel} ${eligibilityScore.toFixed(1)} — must be ${BRAIN_REFERRAL_MIN} or above`,
    }

    const gate2Passed = flaggedCount >= 3 || oigData.excluded || samData.excluded
    const gate2Parts: string[] = []
    if (flaggedCount >= 3) gate2Parts.push(`${flaggedCount} flagged signals`)
    if (oigData.excluded) gate2Parts.push('OIG excluded')
    if (samData.excluded) gate2Parts.push('SAM excluded')
    const gate2: GateResult = {
      label: 'Severity Qualification',
      passed: gate2Passed,
      detail: gate2Passed
        ? gate2Parts.join(', ')
        : `Only ${flaggedCount} flagged signal${flaggedCount === 1 ? '' : 's'} (need 3+), not OIG/SAM excluded`,
    }

    const gate3: GateResult = {
      label: 'Evidence Present',
      passed: flaggedCount >= 1,
      detail: flaggedCount >= 1
        ? `${flaggedCount} flagged signal${flaggedCount === 1 ? '' : 's'} available as evidence`
        : 'No flagged signals — no evidence to support referral',
    }

    const now = Date.now() / 1000
    const ninetyDaysAgo = now - 90 * 24 * 60 * 60
    const recentActive = (refsData.referrals ?? []).filter(
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
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */

  const allGatesPass = gates.length > 0 && gates.every(g => g.passed)
  const passedCount = gates.filter(g => g.passed).length

  const handleProceed = useCallback(() => setPhase('form'), [])

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
      queryClient.invalidateQueries({ queryKey: ['provider', npi] })
    } catch (err: any) {
      setErrorMsg(err?.message || 'Submission failed')
      setPhase('error')
    }
  }, [npi, jurisdiction, mfcuContact, caseNumber, notes, queryClient])

  /* ── Input class ──────────────────────────────────────────────────────── */

  const inputClass =
    'bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none w-full'

  /* ── Render ───────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/providers" className="hover:text-gray-300">Providers</Link>
        <span>/</span>
        <Link to={`/providers/${npi}`} className="hover:text-gray-300 font-mono">{npi}</Link>
        <span>/</span>
        <span className="text-gray-300">MFCU Referral</span>
      </div>

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-white font-bold text-xl">MFCU Referral</h1>
          <p className="text-gray-400 text-sm mt-0.5">{providerName}</p>
        </div>
        <Link
          to={`/providers/${npi}`}
          className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          &larr; Back to Provider
        </Link>
      </div>

      {/* Two-column layout: workflow left, provider summary right */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* ── Left: Workflow phases (2/3 width) ──────────────────────── */}
        <div className="lg:col-span-2 space-y-5">
          {/* Phase: Gate Loading */}
          {phase === 'gate-loading' && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-8 flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">Running eligibility checks...</p>
            </div>
          )}

          {/* Phase: Gate Results */}
          {phase === 'gate-result' && (
            <div className="space-y-4">
              <div className="space-y-3">
                {gates.map((gate, i) => (
                  <div
                    key={i}
                    className={`flex items-start gap-3 p-4 rounded-lg border ${
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
                      <p className={`text-sm font-medium ${gate.passed ? 'text-green-300' : 'text-red-300'}`}>
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
                <Link
                  to={`/providers/${npi}`}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Cancel
                </Link>
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
            </div>
          )}

          {/* Phase: Referral Form */}
          {phase === 'form' && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6 space-y-5">
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
                <Link
                  to={`/providers/${npi}`}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Cancel
                </Link>
                <button
                  onClick={handleSubmit}
                  className="bg-red-700 hover:bg-red-600 text-white font-bold px-6 py-2.5 rounded transition-colors"
                >
                  Submit Referral
                </button>
              </div>
            </div>
          )}

          {/* Phase: Submitting */}
          {phase === 'submitting' && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-8 flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">Submitting referral to MFCU...</p>
            </div>
          )}

          {/* Phase: Success */}
          {phase === 'success' && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-8 flex flex-col items-center justify-center gap-4">
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
              <div className="flex gap-3 mt-2">
                <Link
                  to={`/providers/${npi}`}
                  className="px-4 py-2 text-sm bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-300 rounded transition-colors"
                >
                  Back to Provider
                </Link>
                <Link
                  to="/review"
                  className="px-4 py-2 text-sm bg-blue-700 hover:bg-blue-600 text-white rounded transition-colors"
                >
                  Review Queue
                </Link>
              </div>
            </div>
          )}

          {/* Phase: Error */}
          {phase === 'error' && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-8 flex flex-col items-center justify-center gap-4">
              <div className="w-14 h-14 rounded-full bg-red-900/40 border border-red-700/50 flex items-center justify-center">
                <span className="text-red-400 text-3xl">!</span>
              </div>
              <div className="text-center">
                <p className="text-red-300 font-semibold">Referral Failed</p>
                <p className="text-gray-400 text-sm mt-1">{errorMsg}</p>
              </div>
              <div className="flex gap-3 mt-2">
                <button
                  onClick={() => setPhase('form')}
                  className="px-4 py-2 text-sm bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-300 rounded transition-colors"
                >
                  Try Again
                </button>
                <Link
                  to={`/providers/${npi}`}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 rounded transition-colors"
                >
                  Back to Provider
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* ── Right: Provider summary sidebar (1/3 width) ────────── */}
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
                <span className="text-white text-sm font-mono">
                  {fmt(provider?.spending?.total_paid ?? 0)}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-500 text-xs">Total Claims</span>
                <span className="text-white text-sm font-mono">
                  {(provider?.spending?.total_claims ?? 0).toLocaleString()}
                </span>
              </div>

              {oigData && (
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 text-xs">OIG Status</span>
                  <span className={`text-xs font-bold ${oigData.excluded ? 'text-red-400' : 'text-green-400'}`}>
                    {oigData.excluded ? 'EXCLUDED' : 'Clear'}
                  </span>
                </div>
              )}

              {samData && (
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 text-xs">SAM.gov</span>
                  <span className={`text-xs font-bold ${samData.excluded ? 'text-red-400' : 'text-green-400'}`}>
                    {samData.excluded ? 'EXCLUDED' : 'Clear'}
                  </span>
                </div>
              )}
            </div>

            {/* Flagged signals */}
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

            {/* Existing referrals */}
            {refsData && refsData.referrals.length > 0 && (
              <div className="mt-4 pt-3 border-t border-gray-700">
                <p className="text-gray-500 text-xs mb-2">Previous Referrals ({refsData.total})</p>
                <div className="space-y-1">
                  {refsData.referrals.slice(0, 3).map((r: any, i: number) => (
                    <div key={i} className="text-xs flex items-center justify-between">
                      <span className="text-gray-400 font-mono">{r.referral_id ?? r.id}</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                        r.stage === 'submitted' ? 'bg-blue-900/50 text-blue-300' :
                        r.stage === 'under_investigation' ? 'bg-yellow-900/50 text-yellow-300' :
                        r.stage === 'closed' ? 'bg-gray-800 text-gray-500' :
                        'bg-gray-800 text-gray-400'
                      }`}>
                        {r.stage}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
