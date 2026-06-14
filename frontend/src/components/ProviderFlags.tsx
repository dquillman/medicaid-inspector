import { Link } from 'react-router-dom'
import { useProviderFlags } from '../hooks/useProviderFlags'

/**
 * Cross-page membership badges for a provider: a filament star if the NPI is on
 * the watchlist, and a "BRAIN #n" chip if it's on the Fraud Brain list. Renders
 * nothing when neither applies, so it's safe to drop next to any NPI/name.
 */
export default function ProviderFlags({ npi, className = '' }: { npi: string; className?: string }) {
  const { isWatched, brainRank } = useProviderFlags()
  const watched = isWatched(npi)
  const rank = brainRank(npi)
  if (!watched && rank === undefined) return null

  return (
    <span className={`inline-flex items-center gap-1 align-middle ${className}`}>
      {watched && (
        <span className="text-filament-core" title="On your watchlist" role="img" aria-label="On watchlist">★</span>
      )}
      {rank !== undefined && (
        <Link
          to="/fraud-brain"
          onClick={(e) => e.stopPropagation()}
          title={`On the Fraud Brain list — rank #${rank}`}
          className="text-[10px] font-mono font-semibold leading-none px-1.5 py-0.5 rounded bg-threat-high/15 text-threat-high border border-threat-high/40 hover:bg-threat-high/25 transition-colors"
        >
          BRAIN #{rank}
        </Link>
      )}
    </span>
  )
}
