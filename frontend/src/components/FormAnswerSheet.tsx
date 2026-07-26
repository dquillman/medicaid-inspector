import { useRef, useState } from 'react'

export interface FormField {
  label: string
  value: string
  note?: string
}

/**
 * Field-by-field answers for a state/federal intake form, each independently
 * copyable.
 *
 * Dave, after filing PA's MA Provider Compliance Hotline form: "the step 2 area
 * needs to have all info to copy and paste to the form so I don't need to
 * search the narrative for it." Every value existed only inside the narrative
 * prose, so filling a form meant reading a 3,500-character document and
 * retyping fragments out of it.
 *
 * Each row uses its own hidden textarea + select() + execCommand rather than
 * navigator.clipboard, because clipboard-write is permission-denied on this
 * origin in Chrome — the async API rejects and the execCommand path (which runs
 * inside the click's user activation) is what actually works.
 *
 * Empty value = we do not hold it. Rendered as "leave blank" rather than an
 * empty box, because guessing on a government form is worse than a gap.
 */
export default function FormAnswerSheet({ fields }: { fields: FormField[] }) {
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const [failedIdx, setFailedIdx] = useState<number | null>(null)
  const scratch = useRef<HTMLTextAreaElement>(null)

  const copy = async (text: string, i: number) => {
    setFailedIdx(null)
    const ta = scratch.current
    if (ta) {
      ta.value = text
      ta.focus()
      ta.select()
    }
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text)
        setCopiedIdx(i); setTimeout(() => setCopiedIdx(null), 1500)
        return
      } catch { /* fall through */ }
    }
    try {
      if (document.execCommand('copy')) {
        setCopiedIdx(i); setTimeout(() => setCopiedIdx(null), 1500)
        return
      }
    } catch { /* fall through */ }
    setFailedIdx(i)
  }

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      {/* Off-screen scratch buffer the copy path selects from. */}
      <textarea
        ref={scratch}
        readOnly
        aria-hidden="true"
        tabIndex={-1}
        className="fixed -top-96 left-0 opacity-0 h-px w-px"
      />
      <div className="px-4 py-2.5 border-b border-gray-700 bg-gray-900/40">
        <h3 className="text-sm font-bold text-gray-200">
          Form answers &mdash; copy each field straight across
        </h3>
        <p className="text-[11px] text-gray-500 mt-0.5">
          Everything the state&rsquo;s intake form asks for, derived for this provider.
          Blank means we don&rsquo;t hold it &mdash; leave it blank rather than guess.
        </p>
      </div>
      <div className="divide-y divide-gray-800">
        {fields.map((f, i) => {
          const empty = !f.value
          return (
            <div key={i} className="flex items-start gap-3 px-4 py-2">
              <div className="w-52 shrink-0">
                <p className="text-[11px] text-gray-400 leading-snug">{f.label}</p>
                {f.note && <p className="text-[10px] text-gray-600 leading-snug mt-0.5">{f.note}</p>}
              </div>
              <p className={`flex-1 text-[11px] font-mono leading-snug break-words ${
                empty ? 'text-gray-600 italic' : 'text-amber-300'
              }`}>
                {empty ? 'leave blank' : f.value}
              </p>
              {!empty && (
                <button
                  type="button"
                  onClick={() => copy(f.value, i)}
                  className="shrink-0 px-2 py-1 text-[10px] font-semibold bg-gray-700 hover:bg-amber-600 hover:text-black text-gray-200 rounded transition-colors w-14 text-center"
                >
                  {copiedIdx === i ? '✓' : failedIdx === i ? 'failed' : 'Copy'}
                </button>
              )}
            </div>
          )
        })}
      </div>
      {failedIdx !== null && (
        <p className="px-4 py-2 text-[11px] text-red-400 border-t border-gray-800">
          The browser blocked that copy. Select the value text and press Ctrl+C.
        </p>
      )}
    </div>
  )
}
