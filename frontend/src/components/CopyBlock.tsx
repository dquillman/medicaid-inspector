import { useRef, useState, type ReactNode } from 'react'

/**
 * A block of text the user must get onto their clipboard to paste into an
 * external government form. Used for every referral narrative.
 *
 * Renders a real readonly <textarea>, NOT a <pre>. That matters: the clipboard
 * API can refuse (missing in insecure contexts, rejects with "Document is not
 * focused", blocked by permissions) and when it does there has to be a path
 * that cannot fail. A textarea gives three independent ones:
 *   1. navigator.clipboard.writeText  — the happy path
 *   2. textarea.select() + execCommand('copy') — runs inside the click's user
 *      activation, works where the async API refuses
 *   3. the user clicks in and presses Ctrl+A / Ctrl+C — pure native browser
 *      behaviour with no JS at all, which is why this is a textarea
 *
 * The button reports the REAL outcome. Earlier versions ran
 * `navigator.clipboard?.writeText(text)` and set "Copied ✓" unconditionally, so
 * a silently failed copy was indistinguishable from a good one — Dave pasted
 * into a live state fraud-referral form and got nothing, with no error shown.
 */
export default function CopyBlock({
  text, title, subtitle, buttonLabel = 'Copy', tone = 'primary', rows = 14,
}: {
  text: string
  title: ReactNode
  subtitle?: ReactNode
  buttonLabel?: string
  tone?: 'primary' | 'secondary'
  rows?: number
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [state, setState] = useState<'idle' | 'ok' | 'failed'>('idle')

  const handleCopy = async () => {
    // Always select first: it makes the fallback possible AND leaves the text
    // highlighted so Ctrl+C works even if every programmatic path fails.
    const ta = ref.current
    ta?.focus()
    ta?.select()

    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text)
        setState('ok'); setTimeout(() => setState('idle'), 2000)
        return
      } catch { /* fall through */ }
    }
    try {
      if (document.execCommand('copy')) {
        setState('ok'); setTimeout(() => setState('idle'), 2000)
        return
      }
    } catch { /* fall through */ }
    setState('failed')
  }

  const outer = tone === 'primary'
    ? 'border-2 border-amber-500/60 bg-amber-950/20'
    : 'border border-amber-500/30 bg-amber-950/10'
  const btn = tone === 'primary'
    ? 'bg-amber-600 hover:bg-amber-500'
    : 'bg-amber-700/70 hover:bg-amber-600'

  return (
    <div className={`rounded-lg ${outer}`}>
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-amber-500/30">
        <div>
          <h3 className="text-sm font-bold text-amber-300">{title}</h3>
          {subtitle && <p className="text-[11px] text-amber-200/70 mt-0.5">{subtitle}</p>}
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className={`shrink-0 px-3 py-1.5 text-xs font-semibold ${btn} text-black rounded transition-colors`}
        >
          {state === 'ok' ? 'Copied ✓' : state === 'failed' ? 'Copy failed' : buttonLabel}
        </button>
      </div>
      <p className="px-4 pt-2 text-[11px] text-amber-200/60">
        {state === 'failed'
          ? 'The browser blocked the copy. The text below is already selected — just press Ctrl+C.'
          : 'Tip: you can also click in the box, press Ctrl+A, then Ctrl+C.'}
      </p>
      <textarea
        ref={ref}
        readOnly
        rows={rows}
        value={text}
        onFocus={e => e.currentTarget.select()}
        className="w-full bg-transparent px-4 py-3 text-[11px] font-mono text-gray-300 resize-y focus:outline-none"
      />
    </div>
  )
}
