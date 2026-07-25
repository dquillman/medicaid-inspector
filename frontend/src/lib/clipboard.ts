/**
 * Copy text to the clipboard, reporting whether it ACTUALLY worked.
 *
 * The previous call sites did `navigator.clipboard?.writeText(text)` and then
 * unconditionally showed "Copied ✓". Three ways that lies:
 *   1. `?.` — if `navigator.clipboard` is undefined the call silently no-ops.
 *   2. The returned promise was never awaited, so a rejection (the common one
 *      being "Document is not focused") vanished as an unhandled rejection.
 *   3. Either way the UI claimed success, so a failed copy was indistinguishable
 *      from a good one until you pasted into a government form and got nothing.
 *
 * This awaits the write, falls back to the legacy execCommand path when the
 * async API is unavailable or refuses, and returns false if BOTH fail so the
 * caller can tell the user to select the text manually.
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to the execCommand path below
    }
  }

  // Legacy fallback: works in non-secure contexts and when the async API
  // rejects on focus. Kept off-screen so it never flashes into view.
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-1000px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
