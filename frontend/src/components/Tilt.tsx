/**
 * <Tilt> — wraps content in a NOCTURNE depth scene with pointer parallax.
 *
 *   <Tilt className="card">…</Tilt>
 *
 * Renders a perspective container (`.depth-scene`) around an inner `.tilt`
 * element driven by useTilt. Put your card classes on <Tilt> itself — they land
 * on the tilting element so the existing look is preserved, just with depth.
 *
 * Degrades to a plain elevated card under reduced-motion / touch (the hook
 * no-ops, the static `.tilt` transform stays flat).
 */
import { forwardRef } from 'react'
import type { ReactNode } from 'react'
import { useTilt, type TiltOptions } from '../lib/useTilt'

interface TiltProps extends TiltOptions {
  children: ReactNode
  className?: string
  /** Extra classes on the outer perspective wrapper (layout, spacing, etc.). */
  sceneClassName?: string
  onClick?: () => void
  role?: string
  ariaLabel?: string
}

export const Tilt = forwardRef<HTMLDivElement, TiltProps>(function Tilt(
  { children, className = '', sceneClassName = '', max, lift, onClick, role, ariaLabel },
  _ref,
) {
  const tiltRef = useTilt<HTMLDivElement>({ max, lift })
  return (
    <div className={`depth-scene ${sceneClassName}`}>
      <div
        ref={tiltRef}
        className={`tilt ${className}`}
        onClick={onClick}
        role={role}
        aria-label={ariaLabel}
      >
        {children}
      </div>
    </div>
  )
})
