import { useRef } from 'react'
import { gsap, useGSAP, EASE, DUR, prefersReducedMotion } from '../lib/motion'

interface RevealOpts {
  /** which descendants to stagger (default: direct children). */
  selector?: string
  /** how many actually animate before the rest snap in (tables never wait). */
  cap?: number
}

/**
 * Mount/scroll reveal with a staggered `track` settle. Capped at `cap` items
 * (default 12) — beyond that everything snaps in instantly so a long table
 * never waits on row 80. Reduced motion → everything visible immediately.
 *
 * Returns a ref for the container element.
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>(opts: RevealOpts = {}) {
  const ref = useRef<T>(null)
  const { selector = ':scope > *', cap = 12 } = opts

  useGSAP(
    () => {
      const el = ref.current
      if (!el) return
      const items = Array.from(el.querySelectorAll<HTMLElement>(selector))
      if (!items.length) return

      if (prefersReducedMotion()) {
        gsap.set(items, { opacity: 1, y: 0 })
        return
      }

      const animated = items.slice(0, cap)
      const rest = items.slice(cap)
      gsap.set(items, { opacity: 0, y: 14 })

      const io = new IntersectionObserver(
        (entries, obs) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue
            gsap.to(animated, {
              opacity: 1,
              y: 0,
              duration: DUR.standard,
              ease: EASE.track,
              stagger: DUR.stagger,
            })
            if (rest.length) gsap.set(rest, { opacity: 1, y: 0 })
            obs.disconnect()
            break
          }
        },
        { rootMargin: '0px 0px -8% 0px' },
      )
      io.observe(el)
      return () => io.disconnect()
    },
    { scope: ref },
  )

  return ref
}
