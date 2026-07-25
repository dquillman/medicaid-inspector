import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import Breadcrumbs from '../components/Breadcrumbs'
import Reticle from '../components/Reticle'
import RedactionField from '../components/RedactionField'
import ProviderFlags from '../components/ProviderFlags'
import OigTipButton from '../components/OigTipButton'
import RecencyBadge from '../components/RecencyBadge'
import { threatColor, threatBand, magnitudeGlyph } from '../lib/threat'
import { gsap, useGSAP, EASE, DUR, prefersReducedMotion } from '../lib/motion'
import { queueStatusLabel, QUEUE_STATUS_COLORS } from '../lib/queueStatus'
import type { FraudBrainProvider } from '../lib/types'

/**
 * Read-only case-ledger badge shown next to a candidate in the Fraud Brain
 * ranking. The Brain reads queue_status one-way — this display never writes it
 * and it never affects the brain_score. Title spells out the separation.
 */
/**
 * One-click preparation — automates workflow steps 2–6 for this lead: opens
 * the case at Under Review with the auto-note, corroborates (ring ties, claim
 * patterns, Brain evidence) into an AI-authored case note, and attaches the
 * referral packet. The human-gated steps (Confirm → submit → Reported) stay
 * yours. Long-running (~1–2 min), so the button shows live state.
 */
function PrepareCaseButton({ npi, queueStatus }: { npi: string; queueStatus?: string | null }) {
  const qc = useQueryClient()
  const [state, setState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [msg, setMsg] = useState('')
  // A lead already worked (any ledger status past the default 'open') can't be
  // re-prepared. Show WHY as a plain label instead of a dead disabled button —
  // a silent disabled button reads as "nothing happened" when clicked.
  const alreadyInQueue = !!queueStatus && queueStatus !== 'open'
  if (alreadyInQueue && state === 'idle') {
    return (
      <span
        className="shrink-0 px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-ink-tertiary border border-hairline/60 rounded bg-surface-2/40"
        title={`Already a case (status: ${queueStatus}). Prepare only applies to fresh leads — work this one from the Review Queue.`}
      >
        In review queue
      </span>
    )
  }
  const finishDone = (packetReady: boolean) => {
    setState('done')
    setMsg(packetReady ? 'Prepared — packet ready in Review Queue' : 'Prepared — see Review Queue (open packet there)')
    qc.invalidateQueries({ queryKey: ['fraud-brain'] })
    qc.invalidateQueries({ queryKey: ['review-queue'] })
    qc.invalidateQueries({ queryKey: ['brain-membership'] })
  }

  const run = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (state === 'running' || state === 'done') return
    setState('running')
    setMsg('')
    // Fire preparation, but DON'T trust its HTTP result: prepare runs ~60–90s
    // and 502s through Firebase Hosting's ~60s proxy timeout even though the
    // backend completes fine. Source of truth is polling the case state until
    // prepared_at appears. (Errors on the POST are swallowed on purpose.)
    api.prepareCase(npi).then(
      (r) => { if (r?.ok) finishDone(!!r.packet_ok) },  // fast path (<60s): done immediately
      () => { /* 502/timeout expected for slow providers — polling handles it */ },
    )
    // Poll every 5s for up to ~4 min (prepare is bounded well under this).
    const deadline = Date.now() + 4 * 60 * 1000
    const poll = async () => {
      try {
        const s = await api.prepareState(npi)
        if (s.prepared_at) { finishDone(s.packet_ready); return }
      } catch { /* transient — keep polling */ }
      if (Date.now() > deadline) {
        setState('error')
        setMsg('Still preparing — check the Review Queue in a moment')
        return
      }
      setTimeout(poll, 5000)
    }
    setTimeout(poll, 5000)
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        onClick={run}
        disabled={state === 'running' || state === 'done'}
        title="Auto-run steps 2–6: open case, corroborate (network/claim patterns), attach referral packet (~1–2 min). You still confirm and submit."
        className="shrink-0 px-2 py-1 text-[10px] font-mono uppercase tracking-wider bg-surface-2 hover:bg-hairline border border-hairline hover:border-filament-dim rounded text-ink-secondary hover:text-filament-core transition-colors disabled:opacity-60"
      >
        {state === 'running' ? '⏳ Preparing…' : state === 'done' ? 'Prepared ✓' : 'Prepare Case'}
      </button>
      {msg && (
        <span className={`text-[10px] ${state === 'error' ? 'text-threat-high' : 'text-ink-tertiary'}`}>{msg}</span>
      )}
    </span>
  )
}

function QueueStatusBadge({ status }: { status: string }) {
  const cls = QUEUE_STATUS_COLORS[status] ?? 'text-ink-secondary border-hairline bg-surface-2'
  return (
    <span
      className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] border ${cls}`}
      title="Case-ledger status (set by a human in the Review Queue). Read-only here — it does not affect the Brain score."
    >
      {queueStatusLabel(status)}
    </span>
  )
}

const COMPONENT_LABELS: Record<string, string> = {
  rule_signals: '18 Fraud Signals',
  ml_anomaly: 'ML Anomaly',
  supervised_ml: 'Your-Labels ML',
  corroboration: 'Claim-Level Analyses',
  dollars: 'Dollars at Risk',
  flag_breadth: 'Signal Breadth',
}

const WORKFLOW_STEPS: { title: string; body: string; where?: string }[] = [
  { title: 'Work this list top-down', body: 'Brain score is a confidence level: ~40–60 are strong statistical leads worth investigating. This board is FRESH, UNWORKED leads only — anything you Confirm, Report, or that goes stale/expired drops off automatically.', where: 'You are here — Fraud Brain' },
  { title: 'Prepare the case (one click)', body: 'Opens the case at Investigating, runs the corroboration for you (ego-network ring ties, claim-level patterns, Brain evidence) into a timestamped case note, and attaches the referral packet. Takes 1–2 min. The top 2 fresh leads are prepared automatically every night, so a READY case is usually already waiting.', where: 'Prepare Case button → case shows READY' },
  { title: 'Read what it found', body: 'The auto-investigation note names the intensity multiple ("bills Nx the specialty median per patient"), the codes, any ring ties, and says so honestly when a check could not be run. This is where you decide if it is real — the machine gathered, you judge.', where: 'Review Queue → the case → History' },
  { title: 'Dig deeper if it is close', body: 'Expand each fired flag for its Proof box (claims/bene, peer mean, z-score). Check whether other NPIs share an owner, address, or authorized official.', where: 'Provider page · Network · Fraud Rings · Claim Patterns' },
  { title: 'Confirm it', body: 'If the evidence holds up, set the case to Confirmed. This is human-only — the app cannot do it for you — and it both sharpens the model and drops the lead off this board.', where: 'Review Queue → status dropdown → Confirmed' },
  { title: 'Generate the referral narrative — THIS is the submission', body: 'OIG and MFCU intake are online forms whose main field is a free-text allegation box, so the copy-paste NARRATIVE is what you actually submit. It carries the full address, dollars at risk, per-patient intensity, exclusion check, every fired signal and its regulatory citation — plus a filing guide, derived for THIS provider, telling you exactly which option to pick on each screen. It auto-saves to the case, so it is never lost.', where: 'OIG Tip button (destination: OIG or MFCU)' },
  { title: 'File it', body: 'Follow the filing guide at the top of the tip, then paste everything below the COPY line into the allegation box. The referral packet is your EVIDENCE RECORD, not the submission — attach it only if you want (print it to PDF first; .html is not accepted). OIG never confirms receipt.', where: 'tips.oig.hhs.gov · 1-800-HHS-TIPS · or the state MFCU' },
  { title: 'Close the loop', body: 'Log the tip so you have your own dated record, then set the case to Reported: OIG (or Reported: MFCU — file OIG first if you do both). The case leaves the board and the outcome trains the model.', where: 'OIG Tip → Log as filed · then status → Reported' },
]

function WorkflowPanel() {
  const [open, setOpen] = useState(false)
  return (
    <div className="card border-hairline">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between text-left group"
      >
        <span className="flex items-center gap-2">
          <span className="text-filament-core font-mono text-xs uppercase tracking-wider">Investigation Workflow</span>
          <span className="text-ink-tertiary text-xs">— open a case to a filed OIG referral, step by step</span>
        </span>
        <span className="text-ink-tertiary text-xs font-mono group-hover:text-filament-core transition-colors">
          {open ? 'Hide ▲' : 'Show ▼'}
        </span>
      </button>
      {open && (
        <ol className="mt-4 space-y-3">
          {WORKFLOW_STEPS.map((s, i) => (
            <li key={i} className="flex gap-3">
              <span className="shrink-0 w-6 h-6 rounded-full bg-surface-2 border border-hairline flex items-center justify-center text-xs font-mono text-filament-core">{i + 1}</span>
              <div className="min-w-0">
                <p className="text-sm text-ink-primary font-medium">{s.title}</p>
                <p className="text-xs text-ink-tertiary leading-relaxed mt-0.5">{s.body}</p>
                {s.where && <p className="text-[11px] font-mono text-filament-dim mt-1 uppercase tracking-wider">→ {s.where}</p>}
              </div>
            </li>
          ))}
          <li className="pt-2 mt-1 border-t border-hairline">
            <p className="text-xs text-ink-secondary">
              <span className="font-mono uppercase tracking-wider text-filament-core">TL;DR </span>
              Prepare Case on #1 (or take tonight's READY one) → read the auto-investigation note → Confirmed → OIG Tip → follow its filing guide and paste the narrative at tips.oig.hhs.gov → Log as filed → Reported: OIG.
            </p>
          </li>
        </ol>
      )}
    </div>
  )
}

function BrainScore({ score }: { score: number }) {
  const color = threatColor(score)
  return (
    <span
      role="img"
      aria-label={`Brain score ${score.toFixed(1)} of 100, ${threatBand(score)}`}
      className="font-mono tabular-nums inline-flex items-baseline gap-2"
    >
      <span aria-hidden="true" style={{ color }} className="text-[0.7em]">{magnitudeGlyph(score)}</span>
      <span
        aria-hidden="true"
        className="js-brain-score font-semibold"
        data-score={score.toFixed(1)}
        style={{ color }}
      >
        {score.toFixed(1)}
      </span>
    </span>
  )
}

function RankCard({ rank, p }: { rank: number; p: FraudBrainProvider }) {
  const [expanded, setExpanded] = useState(rank <= 3)
  const maxComponent = Math.max(...Object.values(p.components), 1)
  const prime = rank === 1
  const color = threatColor(p.brain_score)

  return (
    <div
      data-rank-card
      data-rank={rank}
      className={`relative card ${
        prime ? 'border-threat-critical/60 shadow-glow-critical' : p.brain_score >= 75 ? 'border-threat-high/40' : ''
      }`}
    >
      {prime && <Reticle />}
      <div className="flex items-start gap-4">
        <div
          className="font-mono font-bold w-12 text-center shrink-0 leading-none"
          style={{ fontSize: prime ? '2.6rem' : '1.9rem', color: prime ? color : 'var(--hairline-hot)' }}
        >
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <RedactionField delay={rank * 0.06}>
              <Link
                to={`/providers/${p.npi}`}
                className={`font-display font-semibold text-ink-primary hover:text-filament-core transition-colors truncate ${prime ? 'text-lg' : 'text-base'}`}
              >
                {p.provider_name || p.npi}
              </Link>
            </RedactionField>
            <ProviderFlags npi={p.npi} className="ml-1.5" />
            <span className="font-mono text-xs text-ink-tertiary tracking-wide">{p.npi}</span>
            {p.state && (
              <span className="text-[10px] px-2 py-0.5 bg-surface-2 border border-hairline rounded text-ink-secondary font-mono">{p.state}</span>
            )}
            {prime && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-threat-critical border border-threat-critical/60 bg-threat-critical/10">
                Prime Suspect
              </span>
            )}
            {p.queue_status && <QueueStatusBadge status={p.queue_status} />}
            {p.oig_excluded && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-threat-high border border-threat-high/50 bg-threat-high/10">
                OIG Excluded
              </span>
            )}
            {p.deactivated_npi && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-threat-high border border-threat-high/50 bg-threat-high/10">
                Deactivated NPI
              </span>
            )}
            {/* Data-recency badge — annotation only, never a scoring input.
                Stale = recovery lead (FCA reaches back 6 years), not innocent. */}
            <RecencyBadge recency={p.recency} lastActiveMonth={p.last_active_month} dataAgeMonths={p.data_age_months} />
            <div className="ml-auto flex items-center gap-1.5">
              <PrepareCaseButton npi={p.npi} queueStatus={p.queue_status} />
              <OigTipButton npi={p.npi} providerName={p.provider_name} state={p.state} riskScore={p.brain_score} />
            </div>
          </div>
          <p className="text-xs text-ink-tertiary mt-0.5 truncate">{p.specialty || '—'}</p>

          <div className="flex items-center gap-7 mt-3 flex-wrap">
            <div>
              <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.14em] label-stamp">Brain Score</p>
              <div className={prime ? 'text-3xl mt-0.5' : 'text-2xl mt-0.5'}><BrainScore score={p.brain_score} /></div>
            </div>
            <Stat label="Total Paid" value={fmt(p.total_paid)} />
            <Stat label="Signals Fired" value={String(p.flag_count)} />
            <Stat label="Corroborating" value={String(p.corroborating_sources)} />
            {p.last_active_month && <Stat label="Last Active" value={p.last_active_month} />}
          </div>

          {/* Component contribution bars */}
          <div className="mt-4 space-y-1.5">
            {Object.entries(p.components).map(([key, value]) => (
              <div key={key} className="flex items-center gap-3">
                <span className="text-[10px] text-ink-tertiary w-36 shrink-0 uppercase tracking-wider">{COMPONENT_LABELS[key] ?? key}</span>
                <div className="flex-1 h-1.5 bg-surface-2 rounded overflow-hidden">
                  <div
                    className="js-fill h-full rounded"
                    style={{ width: `${Math.min((value / maxComponent) * 100, 100)}%`, background: color, transformOrigin: 'left center' }}
                  />
                </div>
                <span className="text-[10px] font-mono tabular-nums text-ink-tertiary w-9 text-right">{value.toFixed(1)}</span>
              </div>
            ))}
          </div>

          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-3 text-xs text-filament-dim hover:text-filament-core transition-colors"
          >
            {expanded ? '▾ Hide' : '▸ Show'} evidence ({p.evidence.length})
          </button>
          {expanded && (
            <ul className="mt-2 space-y-1.5">
              {p.evidence.map((e, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span className="font-mono tabular-nums text-filament-dim w-10 text-right shrink-0">+{e.points.toFixed(1)}</span>
                  <div>
                    <span className="text-ink-secondary font-medium">{e.source}:</span>{' '}
                    <span className="text-ink-tertiary">{e.detail}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.14em]">{label}</p>
      <p className="text-lg font-mono tabular-nums text-ink-secondary mt-0.5">{value}</p>
    </div>
  )
}

export default function FraudBrain() {
  const boardRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  // Actionable/All view toggle — a VIEW filter only, DEFAULTING to Actionable
  // so the board is always "what needs my attention": resolved cases
  // (Reported/Dismissed — the work is done) and expired providers (past the
  // recovery window) are hidden by default and backfilled by the next ranked
  // candidates, so reporting your whole top-10 refreshes the board instead of
  // leaving a museum of finished cases. STALE stays visible — recovery leads
  // are still live work. "All" is one click away and shows everything ranked;
  // nothing is ever removed from the ranking and ranks never renumber.
  const [actionableOnly, setActionableOnly] = useState(true)
  // The Recompute button must genuinely bypass the backend's 15-min cache —
  // previously it refetched the CACHED board, which made it a no-op. The ref
  // flips to true for exactly one fetch when the button is clicked.
  const forceRef = useRef(false)
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['fraud-brain'],
    // Fetch 25 deep so the Actionable view still fills 10 slots after
    // resolved/expired rows are filtered out.
    queryFn: () => {
      const force = forceRef.current
      forceRef.current = false
      return api.fraudBrainTop(25, force)
    },
    // Kept short + refetch-on-focus so this board and the Review Queue's Brain
    // scores (via useProviderFlags) converge on the same snapshot.
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
  const recompute = () => {
    forceRef.current = true
    void refetch()
    // A forced recompute updates the backend's cached board; refresh the
    // membership map too so the Review Queue's Brain scores don't lag behind.
    void qc.invalidateQueries({ queryKey: ['brain-membership'] })
  }
  const ranked = (data?.top ?? []).map((p, i) => ({ p, rank: i + 1 }))
  const isResolved = (p: FraudBrainProvider) =>
    p.queue_status === 'referred' || p.queue_status === 'tip_filed' ||
    p.queue_status === 'dismissed' || p.queue_status === 'archived'
  const isExcluded = ({ p }: { p: FraudBrainProvider }) => p.recency === 'expired' || isResolved(p)
  const BOARD_SIZE = 10
  const shown = (actionableOnly ? ranked.filter(r => !isExcluded(r)) : ranked).slice(0, BOARD_SIZE)
  const hiddenCount = ranked.slice(0, BOARD_SIZE).filter(isExcluded).length

  // The reveal: cards seat in sequence, score bars sweep up the threat ramp,
  // brain scores count up, #1 locks. Re-runs on Recompute (data identity changes).
  useGSAP(
    () => {
      const board = boardRef.current
      if (!board || !data?.top?.length) return
      const cards = Array.from(board.querySelectorAll<HTMLElement>('[data-rank-card]'))
      if (!cards.length) return

      const setFinal = () => {
        gsap.set(cards, { opacity: 1, y: 0 })
        board.querySelectorAll<HTMLElement>('.js-fill').forEach((f) => gsap.set(f, { scaleX: 1 }))
        board.querySelectorAll<HTMLElement>('.js-brain-score').forEach((el) => { el.textContent = el.dataset.score ?? '' })
      }

      if (prefersReducedMotion()) { setFinal(); return }

      gsap.set(cards, { opacity: 0, y: 24 })
      board.querySelectorAll<HTMLElement>('.js-fill').forEach((f) => gsap.set(f, { scaleX: 0, transformOrigin: 'left center' }))

      const tl = gsap.timeline()
      cards.forEach((card, i) => {
        const first = i === 0
        const at = i * 0.12
        tl.to(card, { opacity: 1, y: 0, duration: first ? DUR.cinematic : DUR.standard, ease: first ? EASE.lock : EASE.track }, at)
        const fills = card.querySelectorAll<HTMLElement>('.js-fill')
        if (fills.length) tl.to(fills, { scaleX: 1, duration: DUR.standard, ease: EASE.acquire, stagger: 0.04 }, at + 0.08)
        const scoreEl = card.querySelector<HTMLElement>('.js-brain-score')
        if (scoreEl) {
          const target = parseFloat(scoreEl.dataset.score ?? '0')
          const o = { v: 0 }
          tl.to(o, { v: target, duration: DUR.cinematic, ease: EASE.acquire, onUpdate: () => { scoreEl.textContent = o.v.toFixed(1) } }, at)
        }
      })
    },
    { dependencies: [data?.top, actionableOnly], scope: boardRef },
  )

  return (
    <div className="space-y-5">
      <Breadcrumbs />

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-display font-bold text-ink-primary tracking-tight">Fraud Brain</h1>
          <p className="text-sm text-ink-tertiary mt-1 max-w-3xl leading-relaxed">
            Cross-source meta-analysis: fuses the 18 rule-based signals, ML anomaly detection,
            claim-level pattern analyses (unbundling, duplicates, impossible volume), pharmacy/DME
            findings, doctor-shopping overlap, diagnosis mismatches, and financial exposure into
            one ranked list of the most probable frauds. Review-Queue confirmed frauds are
            boosted onto the board. OIG-excluded providers are omitted — they're already barred
            and live on the Excluded page — unless they're confirmed fraud, which brings them
            back with their exclusion stacked as evidence.
          </p>
        </div>
        <button
          onClick={recompute}
          disabled={isFetching}
          className="shrink-0 px-3 py-1.5 text-xs font-mono uppercase tracking-wider bg-surface-2 hover:bg-hairline border border-hairline hover:border-filament-dim rounded text-ink-secondary hover:text-filament-core transition-colors disabled:opacity-50"
        >
          {isFetching ? 'Re-acquiring…' : 'Recompute'}
        </button>
      </div>

      {data && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetaStat label="Providers Evaluated" value={data.providers_evaluated.toLocaleString()} />
          <MetaStat
            label="ML Model"
            value={data.ml_model_used ? 'Active' : 'Untrained'}
            tone={data.ml_model_used ? 'on' : 'off'}
          />
          <MetaStat label="Corroborated Providers" value={data.corroborated_providers.toLocaleString()} />
          <MetaStat label="Computed In" value={data.cached ? 'cached' : `${(data.computed_in_ms / 1000).toFixed(1)}s`} />
        </div>
      )}
      {data?.excluded && (data.excluded.confirmed + data.excluded.reported + data.excluded.stale + data.excluded.expired) > 0 && (
        <p className="text-[11px] text-ink-tertiary font-mono">
          Not ranked (no brain rank): {data.excluded.confirmed.toLocaleString()} confirmed ·{' '}
          {data.excluded.reported.toLocaleString()} reported ·{' '}
          {data.excluded.stale.toLocaleString()} stale ·{' '}
          {data.excluded.expired.toLocaleString()} expired
        </p>
      )}

      <WorkflowPanel />

      {isLoading && (
        <div className="card h-40 flex items-center justify-center text-ink-tertiary text-sm font-mono">
          Scoring all providers across every data source…
        </div>
      )}
      {error != null && (
        <div className="card border-threat-critical/60">
          <p className="text-sm text-threat-high">Fraud Brain failed: {String(error)}</p>
        </div>
      )}
      {data?.note && <div className="card"><p className="text-sm text-ink-tertiary">{data.note}</p></div>}

      {/* Actionable/All view toggle — Actionable (default) hides resolved
          (Reported/Dismissed) and expired rows, backfilling with the next
          ranked candidates; All shows everything. Ranks never renumber. */}
      {ranked.length > 0 && hiddenCount > 0 && (
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded border border-hairline overflow-hidden">
            <button
              onClick={() => setActionableOnly(true)}
              className={`px-3 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors ${
                actionableOnly ? 'bg-surface-2 text-filament-core' : 'text-ink-tertiary hover:text-ink-secondary'
              }`}
            >
              Actionable
            </button>
            <button
              onClick={() => setActionableOnly(false)}
              className={`px-3 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors border-l border-hairline ${
                !actionableOnly ? 'bg-surface-2 text-filament-core' : 'text-ink-tertiary hover:text-ink-secondary'
              }`}
            >
              All
            </button>
          </div>
          <span className="text-[11px] text-ink-tertiary font-mono">
            {actionableOnly
              ? `${hiddenCount} resolved/expired case${hiddenCount === 1 ? '' : 's'} hidden, next candidates backfilled — ranks unchanged`
              : `showing all ranked, including reported/dismissed/expired`}
          </span>
        </div>
      )}

      <div ref={boardRef} className="space-y-4">
        {shown.map(({ p, rank }) => <RankCard key={p.npi} rank={rank} p={p} />)}
      </div>
    </div>
  )
}

function MetaStat({ label, value, tone }: { label: string; value: string; tone?: 'on' | 'off' }) {
  return (
    <div className="card py-3">
      <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.14em] label-stamp">{label}</p>
      <p className={`text-xl font-mono tabular-nums mt-0.5 ${tone === 'on' ? 'text-threat-clear' : tone === 'off' ? 'text-ink-tertiary' : 'text-ink-primary'}`}>{value}</p>
    </div>
  )
}
