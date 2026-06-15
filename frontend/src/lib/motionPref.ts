/**
 * Motion preference — a user override on top of the OS prefers-reduced-motion.
 *
 *   'auto' (default) → respect the operating-system setting (508-correct default)
 *   'on'             → force motion ON even if the OS asks to reduce it
 *   'off'            → force motion OFF even if the OS allows it
 *
 * Why an override: some machines (and gov images) ship with "animation effects"
 * disabled, which suppresses the whole NOCTURNE motion layer (card tilt, GSAP,
 * the WebGL hero). 'auto' keeps the accessible default; a user who wants the
 * depth can opt back in without touching their OS.
 *
 * The resolved value drives BOTH JS (useTilt / GSAP / WebGL via
 * webgl.prefersReducedMotion) AND CSS — `applyMotionPref()` mirrors the choice
 * onto <html data-motion>, which the reduced-motion rules in index.css key off
 * so the CSS `!important` backstop can't override a forced-on user.
 */
import { useCallback, useEffect, useState } from 'react'

export type MotionPref = 'auto' | 'on' | 'off'

const KEY = 'mfi_motion_pref'
const EVENT = 'mfi-motion-change'

export function getMotionPref(): MotionPref {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'on' || v === 'off' || v === 'auto') return v
  } catch { /* ignore */ }
  return 'auto'
}

/** Mirror the pref onto <html data-motion> (absent for 'auto'). */
export function applyMotionPref(pref: MotionPref = getMotionPref()): void {
  if (typeof document === 'undefined') return
  const html = document.documentElement
  if (pref === 'auto') html.removeAttribute('data-motion')
  else html.setAttribute('data-motion', pref)
}

export function setMotionPref(pref: MotionPref): void {
  try {
    localStorage.setItem(KEY, pref)
  } catch { /* ignore */ }
  applyMotionPref(pref)
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(EVENT))
}

/** Cycle auto → on → off → auto. Returns the new value. */
export function cycleMotionPref(): MotionPref {
  const next: Record<MotionPref, MotionPref> = { auto: 'on', on: 'off', off: 'auto' }
  const v = next[getMotionPref()]
  setMotionPref(v)
  return v
}

function osReduced(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** The single source of truth: should motion be reduced right now? */
export function resolveReducedMotion(): boolean {
  const p = getMotionPref()
  if (p === 'on') return false
  if (p === 'off') return true
  return osReduced()
}

/** Reactive [pref, setPref] for UI controls — updates across tabs/components. */
export function useMotionPref(): [MotionPref, (p: MotionPref) => void] {
  const [pref, setPref] = useState<MotionPref>(getMotionPref)
  useEffect(() => {
    const onChange = () => setPref(getMotionPref())
    window.addEventListener(EVENT, onChange)
    window.addEventListener('storage', onChange) // sync other tabs
    return () => {
      window.removeEventListener(EVENT, onChange)
      window.removeEventListener('storage', onChange)
    }
  }, [])
  const set = useCallback((p: MotionPref) => setMotionPref(p), [])
  return [pref, set]
}

export const MOTION_CHANGE_EVENT = EVENT
