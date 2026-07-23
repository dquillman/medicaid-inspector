import { useState } from 'react'
import { api } from '../lib/api'

/**
 * Self-contained "generate an HHS-OIG Hotline complaint" button + modal.
 * Reusable on any list row (Fraud Brain, Review Queue, etc.) so a complaint can
 * be drafted without opening the full provider page. Preparation only — copy,
 * log, and open the OIG portal; the human reviews and submits there.
 */
export default function OigTipButton({
  npi, providerName, state, riskScore,
}: { npi: string; providerName?: string; state?: string; riskScore?: number }) {
  const [text, setText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [logged, setLogged] = useState(false)

  const generate = async () => {
    setLoading(true)
    try { const r = await api.oigTip(npi); setText(r.text); setCopied(false); setLogged(false) }
    catch { /* surfaced as no-op; button re-enables */ }
    finally { setLoading(false) }
  }

  return (
    <>
      <button
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); generate() }}
        disabled={loading}
        title="Draft an HHS-OIG Hotline complaint for this provider"
        className="shrink-0 px-2 py-1 text-[10px] font-mono uppercase tracking-wider bg-surface-2 hover:bg-hairline border border-hairline hover:border-filament-dim rounded text-ink-secondary hover:text-filament-core transition-colors disabled:opacity-50"
      >
        {loading ? 'Drafting…' : 'OIG Tip'}
      </button>
      {text && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-void/80 p-4" onClick={() => setText(null)}>
          <div className="bg-surface-1 border border-hairline rounded-xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-glow-filament" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-hairline">
              <h3 className="font-display font-semibold text-ink-primary text-sm truncate">HHS-OIG Hotline Tip — {providerName || npi}</h3>
              <button onClick={() => setText(null)} className="text-ink-tertiary hover:text-ink-primary text-lg leading-none shrink-0 ml-3">×</button>
            </div>
            {/* Destination banner — OIG is FEDERAL (one national hotline), the
                counterpart to the MFCU flow's per-state destination card. */}
            <div className="mx-5 mt-3 bg-blue-950/40 border border-blue-800/50 rounded-lg px-4 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] uppercase tracking-wider text-blue-300/80 font-semibold">Federal destination — HHS-OIG Hotline</p>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300 border border-emerald-700/50">verified</span>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-xs">
                <a href="https://tips.oig.hhs.gov/" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline">tips.oig.hhs.gov ↗</a>
                <span className="text-ink-tertiary">1-800-HHS-TIPS</span>
              </div>
              <p className="text-[11px] text-ink-tertiary mt-1">Auto-drafted below — review, copy, and submit at the portal (the app only logs that you filed).</p>
            </div>
            <pre className="flex-1 overflow-auto px-5 py-4 text-xs font-mono text-ink-secondary whitespace-pre-wrap">{text}</pre>
            <div className="flex items-center gap-2 px-5 py-3 border-t border-hairline">
              <button
                onClick={() => { navigator.clipboard?.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
                className="px-3 py-1.5 text-xs font-medium bg-filament-core text-void rounded hover:bg-filament-core/90 transition-colors"
              >
                {copied ? 'Copied ✓' : 'Copy to clipboard'}
              </button>
              <button
                onClick={async () => { try { await api.logOigTip({ npi, provider_name: providerName ?? '', state: state ?? '', risk_score: riskScore ?? 0 }); setLogged(true) } catch { /* ignore */ } }}
                disabled={logged}
                className="px-3 py-1.5 text-xs font-medium bg-surface-2 border border-hairline text-ink-secondary rounded hover:border-filament-dim transition-colors disabled:opacity-60"
              >
                {logged ? 'Logged ✓' : 'Log as filed'}
              </button>
              <a href="https://tips.oig.hhs.gov/" target="_blank" rel="noopener noreferrer" className="ml-auto text-xs text-filament-dim hover:text-filament-core transition-colors">
                Open OIG submission portal ↗
              </a>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
