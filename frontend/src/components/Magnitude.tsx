import { threatColor, magnitudeGlyph, threatBand } from '../lib/threat'

interface Props {
  /** 0–100 risk / brain score. */
  score: number
  /** show the trailing .decimal (default true). */
  decimal?: boolean
  className?: string
  /** glyph + integer size; decimal renders one step dimmer. */
  size?: 'sm' | 'md' | 'lg' | 'xl'
}

const SIZE: Record<NonNullable<Props['size']>, string> = {
  sm: 'text-xs',
  md: 'text-sm',
  lg: 'text-2xl',
  xl: 'text-[44px] leading-none',
}

/**
 * The colorblind-safe risk primitive: a magnitude glyph (○◔◑◕●) + the score in
 * mono tabular figures, tinted on the continuous threat ramp. Risk is NEVER
 * communicated by hue alone — the glyph carries it for 508.
 */
export default function Magnitude({ score, decimal = true, className = '', size = 'md' }: Props) {
  const color = threatColor(score)
  const int = Math.floor(score)
  const dec = Math.round((score - int) * 10)
  const band = threatBand(score)

  return (
    <span
      className={`font-mono tabular-nums inline-flex items-baseline gap-1.5 ${SIZE[size]} ${className}`}
      role="img"
      aria-label={`Risk ${score.toFixed(1)} of 100, ${band}`}
    >
      <span aria-hidden="true" style={{ color }}>{magnitudeGlyph(score)}</span>
      <span aria-hidden="true">
        <span style={{ color }} className="font-semibold">{int}</span>
        {decimal && <span className="text-ink-tertiary">.{dec}</span>}
      </span>
    </span>
  )
}
