import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { FilerContact } from '../lib/types'

const FIELDS: { key: keyof FilerContact; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'phone', label: 'Phone' },
  { key: 'email', label: 'Email' },
  { key: 'address', label: 'Street address' },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'zip', label: 'ZIP' },
]

/**
 * The filer's own contact details with one-click copy, for the "your
 * information" part of OIG, MFCU and DOJ intake forms (DOJ needs it for a
 * reward). Stored on the user's account, so it follows them across devices.
 * Closed by default: the details are the same every time, and "Copy all"
 * stays in the header so a closed card still does its main job.
 */
export default function ContactCopyCard() {
  const qc = useQueryClient()
  const { data: contact, isLoading } = useQuery({
    queryKey: ['my-contact'],
    queryFn: () => api.myContact(),
    staleTime: 10 * 60_000,
  })
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<FilerContact>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [copied, setCopied] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const scratch = useRef<HTMLTextAreaElement>(null)

  const filled = FIELDS.filter(f => contact?.[f.key])
  const allText = [
    contact?.name,
    contact?.phone,
    contact?.email,
    [contact?.address,
     [[contact?.city, contact?.state].filter(Boolean).join(', '), contact?.zip].filter(Boolean).join(' ')]
      .filter(Boolean).join(', '),
  ].filter(Boolean).join('\n')

  // Same two-path copy as FormAnswerSheet: the async clipboard API is denied on
  // this origin in some Chrome setups, and execCommand inside the click works.
  const copy = async (text: string, id: string) => {
    setFailed(false)
    const ta = scratch.current
    if (ta) { ta.value = text; ta.focus(); ta.select() }
    let ok = false
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); ok = true } catch { /* fall through */ }
    }
    if (!ok) {
      try { ok = document.execCommand('copy') } catch { ok = false }
    }
    if (ok) { setCopied(id); setTimeout(() => setCopied(null), 1500) } else setFailed(true)
  }

  const save = async () => {
    setSaving(true); setSaveError('')
    try {
      const saved = await api.saveMyContact(draft)
      qc.setQueryData(['my-contact'], saved)
      setEditing(false)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const btn = 'shrink-0 px-2 py-1 text-[10px] font-semibold bg-gray-700 hover:bg-amber-600 hover:text-black text-gray-200 rounded transition-colors'

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <textarea ref={scratch} readOnly aria-hidden="true" tabIndex={-1}
        className="fixed -top-96 left-0 opacity-0 h-px w-px" />
      <div className="px-4 py-2.5 border-b border-gray-700 bg-gray-900/40 flex items-center justify-between gap-2">
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open || editing}
          className="text-left group">
          <h3 className="text-sm font-bold text-gray-200 group-hover:text-white">
            <span className="inline-block w-3 text-gray-500">{open || editing ? '▾' : '▸'}</span>
            Your contact info
            {!open && !editing && <span className="ml-2 text-[11px] font-normal text-gray-500">click to show</span>}
          </h3>
          <p className="text-[11px] text-gray-500 ml-3">For the form&rsquo;s &ldquo;your information&rdquo; part. Saved on your account.</p>
        </button>
        <div className="flex gap-2">
          {!editing && allText && (
            <button type="button" className={btn} onClick={() => copy(allText, 'all')}>
              {copied === 'all' ? 'Copied ✓' : 'Copy all'}
            </button>
          )}
          {!editing && (
            <button type="button" className={btn}
              onClick={() => { setDraft({ ...(contact ?? {}) }); setEditing(true); setOpen(true) }}>
              {filled.length ? 'Edit' : 'Add'}
            </button>
          )}
        </div>
      </div>

      {(open || editing) && <>
      {isLoading && <p className="px-4 py-2 text-xs text-gray-500">Loading…</p>}

      {!editing && !isLoading && filled.length === 0 && (
        <p className="px-4 py-2 text-xs text-gray-500">No contact info saved yet. Click Add.</p>
      )}

      {!editing && filled.length > 0 && (
        <div className="divide-y divide-gray-800">
          {filled.map(f => (
            <div key={f.key} className="flex items-center gap-3 px-4 py-1.5">
              <span className="w-28 shrink-0 text-[11px] text-gray-400">{f.label}</span>
              <span className="flex-1 min-w-0 text-[12px] font-mono text-amber-300 break-words">{contact?.[f.key]}</span>
              <button type="button" className={`${btn} w-14 text-center`} onClick={() => copy(contact?.[f.key] ?? '', f.key)}>
                {copied === f.key ? '✓' : 'Copy'}
              </button>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <div className="px-4 py-3 space-y-2">
          {FIELDS.map(f => (
            <label key={f.key} className="flex items-center gap-3">
              <span className="w-28 shrink-0 text-[11px] text-gray-400">{f.label}</span>
              <input
                value={draft[f.key] ?? ''}
                onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-amber-500 focus:outline-none"
              />
            </label>
          ))}
          {saveError && <p className="text-xs text-red-400">{saveError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200" onClick={() => setEditing(false)}>Cancel</button>
            <button type="button" disabled={saving} onClick={save}
              className="px-3 py-1.5 text-xs font-semibold bg-amber-600 hover:bg-amber-500 text-black rounded disabled:opacity-60">
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
      </>}

      {failed && (
        <p className="px-4 py-2 text-[11px] text-red-400 border-t border-gray-800">
          The browser blocked that copy. Select the text and press Ctrl+C.
        </p>
      )}
    </div>
  )
}
