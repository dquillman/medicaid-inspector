import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { api, type HalAction } from '../lib/api'

// HAL slide-out — a global "Ask HAL" panel. HAL itself lives in the qcode ops
// app; the MFI backend relays chat to it (routes/hal.py). When the user is on a
// provider page, the current NPI is auto-attached so HAL can act on it without
// the user restating it.

type Msg = {
  role: 'user' | 'assistant'
  content: string
  actions?: HalAction[]
  error?: boolean
}

// Derive the NPI the user is currently viewing from the URL. Matches
// /providers/<npi> and its sub-routes (/investigate, /ownership, …).
function useCurrentNpi(): string | null {
  const { pathname } = useLocation()
  const m = pathname.match(/^\/providers\/(\d{10})\b/)
  return m ? m[1] : null
}

const SUGGESTIONS = [
  'Who are the 5 riskiest providers right now, and why?',
  'What CPT code is hemodialysis?',
  'Explain the OIG-exclusion signal.',
]

export default function HalPanel() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const npi = useCurrentNpi()

  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to the latest message.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  // Focus the input when the panel opens; Esc closes.
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 250)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    if (open) window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || busy) return
      const next: Msg[] = [...messages, { role: 'user', content: trimmed }]
      setMessages(next)
      setInput('')
      setBusy(true)
      try {
        const res = await api.halChat(
          next.map((m) => ({ role: m.role, content: m.content })),
          npi ?? undefined,
        )
        setMessages((m) => [
          ...m,
          { role: 'assistant', content: res.reply || '(no reply)', actions: res.actions },
        ])
      } catch (e) {
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            content: e instanceof Error ? e.message : 'HAL is unavailable.',
            error: true,
          },
        ])
      } finally {
        setBusy(false)
      }
    },
    [busy, messages, npi],
  )

  return (
    <>
      {/* Floating toggle — the "eye". */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="no-print fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-hairline-hot bg-surface-1/90 px-4 py-2.5 backdrop-blur elev-2 transition-colors hover:border-filament-core/60 group"
        aria-label="Ask HAL"
        title="Ask HAL"
      >
        <span className="relative flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full rounded-full bg-filament-core opacity-60 group-hover:animate-ping" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-filament-core" />
        </span>
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-secondary group-hover:text-ink-primary">
          Ask HAL
        </span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.aside
            key="hal-panel"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="no-print fixed top-0 right-0 z-50 flex h-full w-full max-w-md flex-col border-l border-hairline bg-surface-1 elev-3"
            role="dialog"
            aria-label="HAL assistant"
          >
            {/* Header */}
            <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-filament-core opacity-50 animate-pulse" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-filament-core" />
              </span>
              <div className="flex-1">
                <div className="text-sm font-bold uppercase tracking-[0.2em] text-ink-primary">HAL</div>
                <div className="text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
                  Medicaid Inspector assistant
                </div>
              </div>
              {messages.length > 0 && (
                <button
                  onClick={() => setMessages([])}
                  className="text-[10px] uppercase tracking-wider text-ink-tertiary hover:text-ink-secondary transition-colors"
                  title="Clear conversation"
                >
                  Clear
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="text-ink-tertiary hover:text-ink-primary transition-colors"
                aria-label="Close HAL"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Provider-context chip */}
            {npi && (
              <div className="border-b border-hairline/60 bg-surface-0/40 px-4 py-2">
                <span className="text-[10px] uppercase tracking-[0.15em] text-ink-tertiary">
                  Context ·{' '}
                  <span className="font-mono text-filament-core">NPI {npi}</span>
                </span>
              </div>
            )}

            {/* Messages */}
            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
              {messages.length === 0 && (
                <div className="pt-6 text-center">
                  <p className="text-sm text-ink-secondary">
                    Ask HAL about providers, fraud signals, billing codes, or the riskiest
                    cases — it reads live Medicaid Inspector data.
                  </p>
                  <div className="mt-5 space-y-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="block w-full rounded-lg border border-hairline bg-surface-2/60 px-3 py-2 text-left text-xs text-ink-secondary hover:border-filament-core/40 hover:text-ink-primary transition-colors"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m, i) => (
                <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                  <div className={m.role === 'user' ? 'max-w-[85%]' : 'max-w-[92%]'}>
                    <div
                      className={
                        m.role === 'user'
                          ? 'rounded-2xl rounded-br-sm bg-brand-600 px-3.5 py-2 text-sm text-white'
                          : m.error
                            ? 'rounded-2xl rounded-bl-sm border border-threat-high/40 bg-threat-high/10 px-3.5 py-2 text-sm text-threat-high'
                            : 'rounded-2xl rounded-bl-sm border-l-2 border-filament-core/50 bg-surface-2 px-3.5 py-2 text-sm text-ink-primary'
                      }
                    >
                      <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                    </div>
                    {m.actions && m.actions.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1 pl-1">
                        {m.actions.map((a, j) => (
                          <span
                            key={j}
                            className="rounded border border-hairline bg-surface-0/60 px-1.5 py-0.5 font-mono text-[10px] text-ink-tertiary"
                            title={a.result ? String(a.result).slice(0, 300) : a.name}
                          >
                            {a.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {busy && (
                <div className="flex justify-start">
                  <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm border-l-2 border-filament-core/50 bg-surface-2 px-3.5 py-3">
                    <Dot delay={0} />
                    <Dot delay={0.15} />
                    <Dot delay={0.3} />
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            {/* Composer */}
            <div className="border-t border-hairline px-3 py-3">
              <div className="flex items-end gap-2 rounded-xl border border-hairline bg-surface-2 px-2 py-1.5 focus-within:border-filament-core/50 transition-colors">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      send(input)
                    }
                  }}
                  rows={1}
                  placeholder={npi ? `Ask about NPI ${npi}…` : 'Ask HAL…'}
                  className="max-h-32 flex-1 resize-none bg-transparent px-1.5 py-1 text-sm text-ink-primary placeholder-ink-tertiary focus:outline-none"
                />
                <button
                  onClick={() => send(input)}
                  disabled={busy || !input.trim()}
                  className="mb-0.5 rounded-lg bg-filament-core px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-surface-0 transition-opacity disabled:opacity-30"
                  aria-label="Send"
                >
                  Send
                </button>
              </div>
              <p className="mt-1.5 px-1 text-[10px] text-ink-ghost">
                HAL can make mistakes — verify figures before acting.
              </p>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  )
}

function Dot({ delay }: { delay: number }) {
  return (
    <motion.span
      className="h-1.5 w-1.5 rounded-full bg-filament-core"
      animate={{ opacity: [0.3, 1, 0.3] }}
      transition={{ duration: 1, repeat: Infinity, delay }}
    />
  )
}
