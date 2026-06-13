/**
 * NOCTURNE motion grammar — "surveillance, not celebration."
 *
 * framer-motion keeps route-level enter/exit (App's <AnimatePresence> +
 * <PageTransition>). GSAP owns in-page timelines, count-ups, score bars,
 * reticles and the Fraud Brain FLIP re-rank. The two never animate the same
 * property on the same element.
 *
 * Everything funnels through gsap.matchMedia so a single reduced-motion guard
 * collapses every tween to instant (backstop to the CSS nuke in index.css).
 */
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { prefersReducedMotion } from './webgl'

gsap.registerPlugin(useGSAP)

/** Named easings — the three verbs of the system. */
export const EASE = {
  track: 'power3.out',     // default reveal/settle — the scope settling on target
  acquire: 'expo.out',     // KPI count-ups, big reveals — data rushing in
  lock: 'back.out(1.6)',   // the ONLY overshoot — #1 suspect seating, row snap
} as const

/** Durations (seconds). */
export const DUR = {
  micro: 0.18,
  standard: 0.45,
  cinematic: 0.8,
  stagger: 0.045,
} as const

export { gsap, useGSAP, prefersReducedMotion }
