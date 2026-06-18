import { topFraudOdds, type Flag } from '../lib/signals'

/**
 * "Top Fraud Odds" panel — the most likely fraud type(s) for one provider,
 * ranked by contribution to the composite risk score. Instant (reads the
 * already-computed `flags`); no API call.
 */
export default function TopFraudOdds({
  flags,
  riskScore,
  count = 3,
}: {
  flags?: Flag[] | null
  riskScore?: number | null
  count?: number
}) {
  const odds = topFraudOdds(flags, count)

  const barColor = (s: number) =>
    s >= 66 ? 'bg-red-500' : s >= 33 ? 'bg-amber-500' : 'bg-yellow-600'

  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-ink-secondary uppercase tracking-wide">
          Top Fraud Odds
        </h2>
        {riskScore != null && (
          <span className="text-xs text-ink-tertiary">
            Composite risk <span className="font-mono text-ink-secondary">{Math.round(riskScore)}/100</span>
          </span>
        )}
      </div>

      {odds.length === 0 ? (
        <p className="text-sm text-ink-tertiary">No fraud signals fired for this provider.</p>
      ) : (
        <ol className="space-y-2.5">
          {odds.map((o, i) => (
            <li key={o.signal} className="flex items-start gap-3">
              <span className="text-ink-tertiary font-mono text-sm w-5 shrink-0 pt-0.5">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-ink-primary truncate">{o.label}</span>
                  <span className="text-xs font-mono text-ink-tertiary shrink-0">{o.strength}%</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-surface-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${barColor(o.strength)}`}
                    style={{ width: `${o.strength}%` }}
                  />
                </div>
                {o.reason && <p className="mt-1 text-xs text-ink-tertiary leading-snug">{o.reason}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
