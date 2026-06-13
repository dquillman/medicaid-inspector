import { useCountUp } from '../hooks/useCountUp'

interface Props {
  value: number
  decimals?: number
  prefix?: string
  suffix?: string
  format?: (n: number) => string
  className?: string
}

/**
 * A number that counts up with the `acquire` ease on mount (and re-counts when
 * `value` changes). Mono + tabular by construction. Renders the final value as
 * children so there's no empty flash and no-JS still shows the number; GSAP
 * overwrites textContent during the tween. Reduced motion → no tween.
 */
export default function CountUp({ value, decimals = 0, prefix = '', suffix = '', format, className = '' }: Props) {
  const ref = useCountUp(value, { decimals, prefix, suffix, format })
  const text = format
    ? format(value)
    : value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return (
    <span ref={ref} className={`font-mono tabular-nums ${className}`}>
      {`${prefix}${text}${suffix}`}
    </span>
  )
}
