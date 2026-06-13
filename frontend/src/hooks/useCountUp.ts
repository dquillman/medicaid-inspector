import { useRef } from 'react'
import { gsap, useGSAP, EASE, DUR, prefersReducedMotion } from '../lib/motion'

interface CountUpOpts {
  decimals?: number
  prefix?: string
  suffix?: string
  duration?: number
  /** custom formatter (overrides decimals/locale) — e.g. the money `fmt`. */
  format?: (n: number) => string
}

/**
 * Attach to a <span> to count a number up with the `acquire` ease (data
 * rushing in). Numbers are mono + tabular by convention; pair with a
 * `font-mono tabular-nums` class on the span.
 *
 * Reduced motion → jumps straight to the final value, no tween.
 */
export function useCountUp(value: number, opts: CountUpOpts = {}) {
  const ref = useRef<HTMLSpanElement>(null)
  const { decimals = 0, prefix = '', suffix = '', duration = DUR.cinematic, format } = opts

  const render = (n: number) =>
    `${prefix}${
      format
        ? format(n)
        : n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    }${suffix}`

  useGSAP(
    () => {
      const el = ref.current
      if (!el) return
      if (prefersReducedMotion()) {
        el.textContent = render(value)
        return
      }
      const obj = { v: 0 }
      gsap.to(obj, {
        v: value,
        duration,
        ease: EASE.acquire,
        onUpdate: () => { el.textContent = render(obj.v) },
      })
    },
    { dependencies: [value] },
  )

  return ref
}
