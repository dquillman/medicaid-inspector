import { riskLabel } from '../lib/risk'
import { threatColor, magnitudeGlyph } from '../lib/threat'

interface Props {
  score: number
  size?: 'sm' | 'md' | 'lg'
}

/**
 * NOCTURNE risk readout — the colorblind-safe magnitude glyph (◔◑◕●) + the
 * score in mono tabular figures on the continuous threat ramp, with the
 * established business band label (HIGH/ELEVATED/MED/LOW). Risk is never
 * communicated by hue alone. Used in every table and on ProviderDetail.
 */
export default function RiskScoreBadge({ score, size = 'md' }: Props) {
  const color = threatColor(score)
  const sz = size === 'lg' ? 'text-lg' : size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono tabular-nums font-semibold ${sz}`}
      title={`Risk Score: ${score.toFixed(1)}/100`}
      role="img"
      aria-label={`Risk ${score.toFixed(1)} of 100, ${riskLabel(score)}`}
    >
      <span aria-hidden="true" style={{ color }}>{magnitudeGlyph(score)}</span>
      <span aria-hidden="true" style={{ color }}>{score.toFixed(0)}</span>
      <span aria-hidden="true" className="text-ink-tertiary uppercase tracking-wider text-[0.82em]">{riskLabel(score)}</span>
    </span>
  )
}
