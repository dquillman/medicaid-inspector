/**
 * WebGL guard layer — shared by every three.js scene in the app.
 *
 * An investigation tool runs all day on gov hardware (often integrated GPUs)
 * and must honor Section 508 motion prefs. So every WebGL surface routes its
 * "should I animate / how hard can I push" decisions through here:
 *   - prefers-reduced-motion  -> render a single static frame, no loop
 *   - document hidden / tab in background -> pause the render loop
 *   - perf tier (cores + DPR heuristic) -> cap pixel ratio, drop effects
 *
 * Keep this dependency-free (no three / r3f imports) so plain DOM code and
 * R3F components can both use it.
 */
import { useEffect, useState } from 'react'

export type PerfTier = 'high' | 'mid' | 'low'

/** Synchronous read — safe in SSR-less SPA, guards for older browsers. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Is a WebGL context actually obtainable? (false on locked-down gov machines). */
export function isWebGLAvailable(): boolean {
  if (typeof document === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    )
  } catch {
    return false
  }
}

/** Reactive prefers-reduced-motion (updates if the user flips the OS setting). */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion)
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])
  return reduced
}

/** True while the tab is visible. Used to pause render loops in the background. */
export function useTabVisible(): boolean {
  const [visible, setVisible] = useState(
    typeof document === 'undefined' ? true : !document.hidden,
  )
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])
  return visible
}

/**
 * Cheap, one-shot device classification. We can't reliably benchmark the GPU
 * up front, so use coarse signals: logical cores, device memory (Chromium),
 * and a coarse-pointer/small-screen check for phones/tablets. Conservative on
 * purpose — better to under-promise effects than jank an investigator's table.
 */
export function detectPerfTier(): PerfTier {
  if (typeof navigator === 'undefined') return 'mid'
  const cores = navigator.hardwareConcurrency ?? 4
  // deviceMemory is Chromium-only and approximate (GB).
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4
  const coarse =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(pointer: coarse)').matches === true
  const small = typeof window !== 'undefined' && window.innerWidth < 900

  if (coarse || small || cores <= 4 || mem <= 4) return 'low'
  if (cores <= 8 || mem <= 8) return 'mid'
  return 'high'
}

/** Memoized tier (device class doesn't change within a session). */
let _tier: PerfTier | null = null
export function getPerfTier(): PerfTier {
  if (_tier === null) _tier = detectPerfTier()
  return _tier
}

/**
 * The pixel-ratio cap to hand R3F's <Canvas dpr={...}>. High-DPI displays on
 * weak GPUs are the #1 cause of WebGL jank, so we clamp hard on low tiers.
 */
export function dprCap(tier: PerfTier = getPerfTier()): [number, number] {
  switch (tier) {
    case 'high': return [1, 2]
    case 'mid':  return [1, 1.5]
    case 'low':  return [1, 1]
  }
}

/**
 * One call that answers "should this scene render a live loop at all?" — false
 * when the user asked for reduced motion. Callers should still render ONE
 * static frame (frameloop="never" + a single invalidate) so the visual exists
 * without animating.
 */
export function shouldAnimateWebGL(reduced: boolean, visible: boolean): boolean {
  return !reduced && visible
}
