import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import Breadcrumbs from '../components/Breadcrumbs'

export default function Methods() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['methods'],
    queryFn: () => api.methods(),
    staleTime: 10 * 60_000,
  })

  return (
    <div className="space-y-5 max-w-4xl">
      <Breadcrumbs />

      <div>
        <h1 className="text-xl font-display font-bold text-ink-primary tracking-tight">Methodology</h1>
        <p className="text-sm text-ink-tertiary mt-1 leading-relaxed">
          Exactly how Medicaid Inspector scores providers — every signal, its regulatory basis, and
          its measured precision. Detection your AG's office can read; nothing here is provider-identifying.
        </p>
      </div>

      {isLoading && <div className="card h-32 flex items-center justify-center text-ink-tertiary text-sm font-mono">Loading methodology…</div>}
      {error != null && <div className="card border-threat-critical/60"><p className="text-sm text-threat-high">Failed to load: {String(error)}</p></div>}

      {data && (
        <>
          {/* Provenance */}
          <div className="card space-y-3">
            <h2 className="text-base font-display font-semibold text-ink-primary flex items-center gap-2">
              Data Provenance
              {data.provenance.is_real_medicaid && (
                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-[0.14em] text-threat-clear border border-threat-clear/50 bg-threat-clear/10">Real Medicaid Data</span>
              )}
            </h2>
            <p className="text-sm text-ink-secondary"><span className="text-ink-tertiary">Core dataset:</span> {data.provenance.core_dataset}</p>
            <p className="text-sm text-ink-secondary">{data.provenance.coverage}</p>
            <div>
              <p className="text-[10px] text-ink-tertiary uppercase tracking-[0.14em] label-stamp mb-1">Known limits (disclosed in every tip)</p>
              <ul className="text-xs text-ink-tertiary space-y-1 list-disc pl-5">
                {data.provenance.known_limits.map((l, i) => <li key={i}>{l}</li>)}
              </ul>
            </div>
            <p className="text-xs text-ink-tertiary border-l-2 border-filament-dim pl-3">{data.provenance.medicare_proxy_note}</p>
            <p className="text-xs text-ink-tertiary">
              <span className="text-ink-secondary">Enrichment:</span> {data.provenance.enrichment_sources.join(' · ')}
            </p>
          </div>

          {/* Composite methodology */}
          <div className="card">
            <h2 className="text-base font-display font-semibold text-ink-primary mb-2">Composite Score</h2>
            <p className="text-sm text-ink-secondary leading-relaxed">{data.composite_methodology}</p>
          </div>

          {/* Signals */}
          <div>
            <h2 className="text-base font-display font-semibold text-ink-primary mb-3">
              The {data.signal_count} Fraud Signals
            </h2>
            <div className="space-y-3">
              {data.signals.map((s) => (
                <div key={s.signal} className="card">
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="text-sm font-semibold text-ink-primary">{s.label}</h3>
                    {s.precision != null ? (
                      <span className="shrink-0 text-xs font-mono tabular-nums text-ink-secondary" title={`${s.true_positives} TP / ${s.false_positives} FP over ${s.sample_size} dispositions`}>
                        precision <span className="text-threat-clear font-semibold">{(s.precision * 100).toFixed(0)}%</span>
                        <span className="text-ink-tertiary"> (n={s.sample_size})</span>
                      </span>
                    ) : (
                      <span className="shrink-0 text-[10px] font-mono uppercase tracking-wider text-ink-tertiary">precision: not yet measured</span>
                    )}
                  </div>
                  <p className="text-xs text-ink-tertiary mt-1.5 leading-relaxed">{s.explanation}</p>
                  {s.citations.length > 0 && (
                    <p className="text-[11px] font-mono text-filament-dim mt-2">{s.citations.join(' · ')}</p>
                  )}
                  {s.weight_adjustment < 1 && (
                    <p className="text-[10px] text-threat-medium mt-1.5">
                      Auto-dampened to {(s.weight_adjustment * 100).toFixed(0)}% weight (low measured precision)
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>

          <p className="text-[11px] text-ink-tertiary">
            Precision figures derive from {data.feedback_totals.dispositions.toLocaleString()} analyst dispositions
            ({data.feedback_totals.true_positive_signal_hits.toLocaleString()} confirmed / {data.feedback_totals.false_positive_signal_hits.toLocaleString()} cleared signal hits).
            Scores are a relative ranking, not a calibrated fraud probability.
          </p>
        </>
      )}
    </div>
  )
}
