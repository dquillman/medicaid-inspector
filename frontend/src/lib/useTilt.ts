/**
 * useTilt — NOCTURNE pointer-parallax for cards/panels.
 *
 * Drives a small rotateX/rotateY on the target element so it leans toward the
 * cursor, then eases back on release. Compositor-only transforms (the element
 * carries `.tilt`, which owns the transform + transition) so it stays at 60fps
 * and never triggers layout/paint while tracking.
 *
 * Honors the design-system guardrails: bails entirely under reduced-motion and
 * on coarse (touch) pointers — those users get the static elevated card.
 */
import { useEffect, useRef } from 'react'
import { useReducedMotion } from './webgl'

export interface TiltOptions {
  /** Peak rotation at the card edge, in degrees. Keep it subtle. */
  max?: number
  /** Extra lift toward the viewer while hovered, in px (translateZ). */
  lift?: number
}

export function useTilt<T extends HTMLElement = HTMLDivElement>(
  opts: TiltOptions = {},
) {
  const { max = 6, lift = 6 } = opts
  const ref = useRef<T | null>(null)
  // Reactive: re-runs the effect when the user flips the Motion toggle (or OS
  // setting), so the tilt attaches/detaches live without a reload.
  const reduced = useReducedMotion()

  useEffect(() => {
    const el = ref.current
    if (!el) return

    // Skip on touch devices and for users who asked for reduced motion.
    const coarse =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(pointer: coarse)').matches
    if (coarse || reduced) return

    let raf = 0
    let pending: { rx: number; ry: number } | null = null

    const apply = () => {
      raf = 0
      if (!pending) return
      el.style.setProperty('--tilt-x', `${pending.rx.toFixed(2)}deg`)
      el.style.setProperty('--tilt-y', `${pending.ry.toFixed(2)}deg`)
    }

    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      // -0.5 … 0.5 from card center
      const px = (e.clientX - r.left) / r.width - 0.5
      const py = (e.clientY - r.top) / r.height - 0.5
      // Lean toward the cursor: top → tilt back, right → tilt right.
      pending = { rx: -py * max * 2, ry: px * max * 2 }
      if (!raf) raf = requestAnimationFrame(apply)
    }

    const onEnter = () => {
      el.classList.add('is-tilting')
      if (lift) el.style.transform =
        `perspective(1100px) rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg)) translateZ(${lift}px)`
    }

    const onLeave = () => {
      el.classList.remove('is-tilting')
      el.style.removeProperty('transform') // fall back to the .tilt CSS rule
      el.style.setProperty('--tilt-x', '0deg')
      el.style.setProperty('--tilt-y', '0deg')
      pending = null
    }

    el.addEventListener('pointerenter', onEnter)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerleave', onLeave)
    return () => {
      el.removeEventListener('pointerenter', onEnter)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerleave', onLeave)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [max, lift, reduced])

  return ref
}
