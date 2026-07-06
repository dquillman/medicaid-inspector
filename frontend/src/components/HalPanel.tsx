import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { api, type HalAction } from '../lib/api'

// HAL slide-out — a global "Ask HAL" panel. HAL itself lives in the qcode ops
// app; the MFI backend relays chat to it (routes/hal.py). When the user is on a
// provider page, the current NPI is auto-attached so HAL can act on it without
// the user restating it.
//
// Voice I/O mirrors qcode's HalConsole: speechSynthesis output (soft, unhurried
// — rate .82 / pitch .85, pause/resume keep-alive for Chrome's ~15s cutoff) and
// webkitSpeechRecognition mic input. The red lens is the HAL 9000 eye.

type Msg = {
  role: 'user' | 'assistant'
  content: string
  actions?: HalAction[]
  error?: boolean
}

// Minimal local typing for the vendor-prefixed Web Speech recognition API.
type Recognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
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

const VOICE_KEY = 'mfi-hal-voice' // persisted VOICE ON/OFF preference

// The HAL 9000 lens — red radial eye with breathe/thinking/speaking states.
function HalEye({ size, state }: { size: number; state: 'idle' | 'thinking' | 'speaking' }) {
  return (
    <span
      className={`hal-lens hal-${state}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span className="hal-glint" />
    </span>
  )
}

export default function HalPanel() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [listening, setListening] = useState(false)
  const [voiceOn, setVoiceOn] = useState(() => localStorage.getItem(VOICE_KEY) !== 'off')
  const [canListen, setCanListen] = useState(false)
  const npi = useCurrentNpi()

  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recRef = useRef<Recognition | null>(null)
  const voiceOnRef = useRef(voiceOn)
  voiceOnRef.current = voiceOn

  useEffect(() => {
    setCanListen('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)
  }, [])

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

  // ---- HAL's voice (qcode HalConsole pattern) -------------------------------
  const speak = useCallback((text: string) => {
    if (!voiceOnRef.current || !('speechSynthesis' in window)) return
    const synth = window.speechSynthesis
    synth.cancel()

    const utt = new SpeechSynthesisUtterance(text)
    utt.lang = 'en-US'
    // HAL: soft, unhurried, perfectly even.
    utt.rate = 0.82
    utt.pitch = 0.85
    utt.volume = 1

    // Best-effort voice pick — never block on voiceschanged (Chrome can
    // transiently return an empty list and never re-fire the event).
    const voices = synth.getVoices()
    const preferred = [
      'Microsoft Guy Online (Natural) - English (United States)',
      'Microsoft Davis Online (Natural) - English (United States)',
      'Microsoft David - English (United States)',
      'Microsoft Mark - English (United States)',
      'Google US English',
      'Daniel',
      'Alex',
    ]
    const pick =
      preferred.map((n) => voices.find((v) => v.name === n)).find(Boolean) ??
      voices.find((v) => v.lang === 'en-US') ??
      voices.find((v) => v.lang.startsWith('en'))
    if (pick) utt.voice = pick

    // Chrome silently halts synthesis after ~15s; periodic pause/resume keeps
    // long replies alive. Cleared the moment speech ends.
    let keepAlive: ReturnType<typeof setInterval> | null = setInterval(() => {
      if (!synth.speaking) {
        if (keepAlive) clearInterval(keepAlive)
        keepAlive = null
        return
      }
      synth.pause()
      synth.resume()
    }, 10000)
    const finish = () => {
      if (keepAlive) {
        clearInterval(keepAlive)
        keepAlive = null
      }
      setSpeaking(false)
    }
    utt.onend = finish
    utt.onerror = finish
    utt.onstart = () => setSpeaking(true)
    synth.speak(utt)
  }, [])

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
        const reply = res.reply || '(no reply)'
        setMessages((m) => [...m, { role: 'assistant', content: reply, actions: res.actions }])
        speak(reply)
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
    [busy, messages, npi, speak],
  )

  // ---- HAL's ears -----------------------------------------------------------
  const listen = useCallback(() => {
    if (!canListen || listening || busy) return
    window.speechSynthesis?.cancel() // don't listen to ourselves
    const w = window as unknown as Record<string, unknown>
    const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as new () => Recognition
    const rec = new Ctor()
    rec.lang = 'en-US'
    rec.continuous = false
    rec.interimResults = false
    rec.onresult = (e) => {
      const t = e.results[0]?.[0]?.transcript ?? ''
      if (t) void send(t)
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recRef.current = rec
    setListening(true)
    rec.start()
  }, [canListen, listening, busy, send])

  // Stop audio when the panel closes or unmounts.
  useEffect(() => {
    if (!open) {
      window.speechSynthesis?.cancel()
      recRef.current?.stop()
      setSpeaking(false)
    }
  }, [open])
  useEffect(
    () => () => {
      window.speechSynthesis?.cancel()
      recRef.current?.stop()
    },
    [],
  )

  const eyeState: 'idle' | 'thinking' | 'speaking' = speaking ? 'speaking' : busy ? 'thinking' : 'idle'
  const status = listening ? 'LISTENING' : speaking ? 'SPEAKING' : busy ? 'PROCESSING' : 'OPERATIONAL'

  return (
    <>
      <style>{`
        .hal-lens {
          position: relative; display: inline-block; border-radius: 9999px; flex: none;
          background: radial-gradient(circle at 50% 44%,
            #fff7d6 0%, #ffc24a 5%, #ff5a00 16%, #d61a00 30%,
            #6e0700 52%, #1c0100 74%, #000 92%);
          box-shadow: 0 0 14px 3px rgba(255,42,0,.55), 0 0 34px 7px rgba(255,42,0,.22);
          animation: halBreathe 4.5s ease-in-out infinite;
        }
        .hal-lens.hal-thinking { animation: halBreathe 1.4s ease-in-out infinite; }
        .hal-lens.hal-speaking { animation: halSpeak .55s ease-in-out infinite; }
        .hal-glint {
          position: absolute; width: 22%; height: 13%; border-radius: 9999px;
          top: 28%; left: 36%; background: rgba(255,255,255,.85);
          filter: blur(1px); transform: rotate(-25deg);
        }
        @keyframes halBreathe {
          0%, 100% { filter: brightness(.92); }
          50% { filter: brightness(1.12); }
        }
        @keyframes halSpeak {
          0%, 100% { filter: brightness(.95);
            box-shadow: 0 0 12px 2px rgba(255,42,0,.5), 0 0 30px 6px rgba(255,42,0,.2); }
          50% { filter: brightness(1.35);
            box-shadow: 0 0 20px 5px rgba(255,42,0,.85), 0 0 50px 12px rgba(255,42,0,.38); }
        }
      `}</style>

      {/* Floating toggle — the eye. */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="no-print fixed bottom-5 right-5 z-40 flex items-center gap-2.5 rounded-full border border-hairline-hot bg-surface-1/90 px-4 py-2.5 backdrop-blur elev-2 transition-colors hover:border-threat-critical/60 group"
        aria-label="Ask HAL"
        title="Ask HAL"
      >
        <HalEye size={16} state={eyeState} />
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
            {/* Header — the eye, name, live status */}
            <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
              <HalEye size={34} state={eyeState} />
              <div className="flex-1">
                <div className="text-sm font-bold uppercase tracking-[0.3em] text-ink-primary">HAL 9000</div>
                <div className="text-[10px] uppercase tracking-[0.25em] text-ink-tertiary">{status}</div>
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
                        className="block w-full rounded-lg border border-hairline bg-surface-2/60 px-3 py-2 text-left text-xs text-ink-secondary hover:border-threat-critical/40 hover:text-ink-primary transition-colors"
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
                            : 'rounded-2xl rounded-bl-sm border-l-2 border-threat-critical/60 bg-surface-2 px-3.5 py-2 text-sm text-ink-primary'
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
                  <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm border-l-2 border-threat-critical/60 bg-surface-2 px-3.5 py-3">
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
              <div className="flex items-end gap-2 rounded-xl border border-hairline bg-surface-2 px-2 py-1.5 focus-within:border-threat-critical/50 transition-colors">
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
                  placeholder={listening ? 'Listening…' : npi ? `Ask about NPI ${npi}…` : 'Speak to HAL…'}
                  className="max-h-32 flex-1 resize-none bg-transparent px-1.5 py-1 text-sm text-ink-primary placeholder-ink-tertiary focus:outline-none"
                />
                {canListen && (
                  <button
                    onClick={listen}
                    disabled={busy || listening}
                    className={`mb-0.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors disabled:opacity-40 ${
                      listening
                        ? 'border-threat-critical text-threat-critical shadow-[0_0_12px_rgba(215,38,61,0.4)]'
                        : 'border-hairline text-ink-tertiary hover:border-threat-critical/50 hover:text-ink-secondary'
                    }`}
                    title="Talk to HAL with your microphone"
                    aria-label="Voice input"
                  >
                    {listening ? '● Mic' : 'Mic'}
                  </button>
                )}
                <button
                  onClick={() => send(input)}
                  disabled={busy || !input.trim()}
                  className="mb-0.5 rounded-lg bg-threat-critical px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-white transition-opacity disabled:opacity-30"
                  aria-label="Send"
                >
                  Send
                </button>
              </div>
              <div className="mt-1.5 flex items-center justify-between px-1">
                <p className="text-[10px] text-ink-ghost">
                  HAL can make mistakes — verify figures before acting.
                </p>
                <button
                  onClick={() => {
                    if (voiceOn) window.speechSynthesis?.cancel()
                    setVoiceOn((v) => {
                      localStorage.setItem(VOICE_KEY, v ? 'off' : 'on')
                      return !v
                    })
                  }}
                  className="text-[10px] uppercase tracking-wider text-ink-tertiary hover:text-ink-secondary transition-colors"
                  title="Toggle HAL's voice"
                >
                  Voice {voiceOn ? 'On' : 'Off'}
                </button>
              </div>
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
      className="h-1.5 w-1.5 rounded-full bg-threat-critical"
      animate={{ opacity: [0.3, 1, 0.3] }}
      transition={{ duration: 1, repeat: Infinity, delay }}
    />
  )
}
