import { useRef, type ReactNode } from 'react'
import { gsap, useGSAP, EASE, DUR, prefersReducedMotion } from '../lib/motion'

interface Props {
  children: ReactNode
  /** seconds to wait before the redaction bar wipes away. */
  delay?: number
  className?: string
}

/**
 * "Declassification" reveal — the value sits under a solid ink-ghost bar that
 * wipes left→right to expose it (the file coming out of redaction). Replaces
 * the old shimmer for hero reveals.
 *
 * The bar is a compositor-only scaleX transform (no layout/paint thrash), and
 * under reduced motion the value simply shows with no bar.
 */
export default function RedactionField({ children, delay = 0, className = '' }: Props) {
  const scope = useRef<HTMLSpanElement>(null)
  const barRef = useRef<HTMLSpanElement>(null)

  useGSAP(
    () => {
      const bar = barRef.current
      if (!bar) return
      if (prefersReducedMotion()) {
        gsap.set(bar, { display: 'none' })
        return
      }
      gsap.set(bar, { transformOrigin: 'right center', scaleX: 1 })
      gsap.to(bar, { scaleX: 0, duration: DUR.standard, ease: EASE.track, delay })
    },
    { scope, dependencies: [delay] },
  )

  return (
    <span ref={scope} className={`relative inline-block ${className}`}>
      {children}
      <span
        ref={barRef}
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[2px] bg-ink-ghost"
      />
    </span>
  )
}
