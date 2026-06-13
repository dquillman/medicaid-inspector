interface Props {
  /** stroke color — defaults to the filament accent. */
  color?: string
  /** corner arm length in px. */
  arm?: number
  className?: string
}

/**
 * Surveillance corner-brackets that frame an acquired target (Fraud Brain #1,
 * the selected cytoscape node). Pure SVG so it stays crisp and AA-safe; sits in
 * an absolutely-positioned overlay (parent should be `relative`).
 */
export default function Reticle({ color = 'var(--filament-core)', arm = 16, className = '' }: Props) {
  const s = 2 // stroke
  return (
    <svg
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 h-full w-full ${className}`}
      preserveAspectRatio="none"
      viewBox="0 0 100 100"
    >
      {/* corners drawn in a 0..100 box; vector-effect keeps stroke crisp */}
      <g fill="none" stroke={color} strokeWidth={s} vectorEffect="non-scaling-stroke" strokeLinecap="square">
        {/* top-left */}
        <path d={`M0 ${arm} V0 H${arm}`} />
        {/* top-right */}
        <path d={`M${100 - arm} 0 H100 V${arm}`} />
        {/* bottom-right */}
        <path d={`M100 ${100 - arm} V100 H${100 - arm}`} />
        {/* bottom-left */}
        <path d={`M${arm} 100 H0 V${100 - arm}`} />
      </g>
    </svg>
  )
}
