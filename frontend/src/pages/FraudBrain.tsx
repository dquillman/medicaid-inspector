import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import Breadcrumbs from '../components/Breadcrumbs'
import Reticle from '../components/Reticle'
import RedactionField from '../components/RedactionField'
import ProviderFlags from '../components/ProviderFlags'
import OigTipButton from '../components/OigTipButton'
import { threatColor, threatBand, magnitudeGlyph } from '../lib/threat'
import { gsap, useGSAP, EASE, DUR, prefersReducedMotion } from '../lib/motion'
import { queueStatusLabel, QUEUE_STATUS_COLORS } from '../lib/queueStatus'
import type { FraudBrainProvider } from '../lib/types'

/**
 * Read-only case-ledger badge shown next to a candidate in the Fraud Brain
 * ranking. The Brain reads queue_status one-way — this display never writes it
 * and it never affects the brain_score. Title spells out the separation.
 */
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
  { title: 'Work this list top-down', body: 'Score is a confidence level: 85+ is proven/near-proven (OIG-excluded or confirmed); ~40–60 are strong statistical leads worth investigating.', where: 'You are here — Fraud Brain' },
  { title: 'Open the lead & read the evidence', body: 'Check Top Fraud Odds, then expand each fired flag to see its Proof box (claims/bene, peer mean, z-score) and the "bills Nx the specialty median per patient" line — that one sentence is your case.', where: 'Click the provider name' },
  { title: 'Corroborate', body: 'Is it tied to other NPIs (a ring)? Confirm the specific abusive codes before you commit time.', where: 'Network · Fraud Rings · Claim Patterns' },
  { title: 'Capture it', body: 'Open a case and set status to Under Review with a one-line note (the intensity multiple + the codes).', where: 'Add to Review button → Review Queue' },
  { title: 'Build the case', body: 'Add notes, log hours, attach documents. Move the status along as you verify — confirming here sharpens the Brain next time.', where: 'Review Queue → the case' },
  { title: 'Generate the referral packet', body: 'Bundles every signal with its proof section, dollars at risk, and methodology — your submission document.', where: 'Referral Packet / Export button' },
  { title: 'Report to HHS-OIG', body: 'Submit the packet with provider name + NPI, the scheme in one line, and the dollars at risk. Note: OIG never confirms receipt — keep your own record in OIG Tips.', where: 'TIPS.HHS.GOV · 1-800-HHS-TIPS · log in OIG Tips' },
  { title: 'Close the loop', body: 'Mark the case Submitted/Confirmed so your board stays clean and the model learns from the outcome.', where: 'Review Queue' },
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
              Open #1 → expand the proof → Add to Review → Referral Packet → submit to HHS-OIG (1-800-HHS-TIPS) → mark it submitted.
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
            <div className="ml-auto">
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
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['fraud-brain'],
    queryFn: () => api.fraudBrainTop(10),
    staleTime: 5 * 60_000,
  })

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
    { dependencies: [data?.top], scope: boardRef },
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
          onClick={() => refetch()}
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

      <div ref={boardRef} className="space-y-4">
        {data?.top.map((p, i) => <RankCard key={p.npi} rank={i + 1} p={p} />)}
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
