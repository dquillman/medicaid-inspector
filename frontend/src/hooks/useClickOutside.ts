import { useEffect, type RefObject } from 'react'

/**
 * Calls `callback` when a mousedown event occurs outside the element
 * referenced by `ref`. Useful for closing dropdowns and modals.
 */
export function useClickOutside(
  ref: RefObject<HTMLElement | null>,
  callback: () => void,
) {
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        callback()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [ref, callback])
}
