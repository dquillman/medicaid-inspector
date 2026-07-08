import { useState, useRef, useEffect, useCallback, type Dispatch, type SetStateAction } from 'react'
import { useLocation, useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { api, type HalAction, type HalProvider } from '../lib/api'
import { buildReportSlideshow } from './halReport'

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
  providers?: HalProvider[]
  error?: boolean
}

// Render assistant text, turning any known provider name into a link to its
// page (/providers/<npi>). Longest names first so overlapping names match
// greedily; case-insensitive; each name linked on every occurrence.
function LinkifiedText({ text, providers }: { text: string; providers?: HalProvider[] }) {
  if (!providers || providers.length === 0) {
    return <p className="whitespace-pre-wrap leading-relaxed">{text}</p>
  }
  const uniq = Array.from(new Map(providers.map((p) => [p.name.toLowerCase(), p])).values())
    .filter((p) => p.name && p.name.length >= 3)
    .sort((a, b) => b.name.length - a.name.length)
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(`(${uniq.map((p) => esc(p.name)).join('|')})`, 'gi')
  const byLower = new Map(uniq.map((p) => [p.name.toLowerCase(), p]))
  const parts = text.split(pattern)
  return (
    <p className="whitespace-pre-wrap leading-relaxed">
      {parts.map((part, i) => {
        const hit = byLower.get(part.toLowerCase())
        return hit ? (
          <Link
            key={i}
            to={`/providers/${hit.npi}`}
            className="font-medium text-brand-400 underline decoration-dotted underline-offset-2 hover:text-brand-300"
            title={`Open provider ${hit.npi}`}
          >
            {part}
          </Link>
        ) : (
          <span key={i}>{part}</span>
        )
      })}
    </p>
  )
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
  onerror: ((e: { error?: string }) => void) | null
}

// Human-readable causes for SpeechRecognition failures. Without this the mic
// button fails silently (onerror just reset state) and reads as "broken".
const MIC_ERRORS: Record<string, string> = {
  'not-allowed':
    'Microphone access is blocked for this site. Click the lock icon in the address bar → Site settings → Microphone → Allow, then try again. (Tabs opened by automation tools often have the prompt suppressed — open the app in a regular window if so.)',
  'service-not-allowed':
    'The browser blocked the speech service for this site — check Site settings → Microphone.',
  'audio-capture': 'No microphone was found. Check that a mic is connected and not in use by another app.',
  'network': 'The speech service could not be reached — Chrome speech recognition needs internet.',
  'no-speech': "I didn't catch anything — try again, a bit closer to the mic.",
}

// Derive the NPI the user is currently viewing from the URL. Matches
// /providers/<npi> and its sub-routes (/investigate, /ownership, …).
function useCurrentNpi(): string | null {
  const { pathname } = useLocation()
  const m = pathname.match(/^\/providers\/(\d{10})\b/)
  return m ? m[1] : null
}

// Parse a navigation command ("go to the Network page", "open providers",
// "show me anomalies") and resolve it to a route by matching the app's own
// in-app links (the sidebar NavLinks). Returns null for anything that isn't a
// navigation command, so real questions still reach HAL's brain. Client-side:
// HAL drives React Router itself, since the backend can't move the browser.
function halFindRoute(text: string): { path: string; label: string } | null {
  const t = text.toLowerCase().trim().replace(/[.!?]+$/, '')
  let target: string | null = null
  const m = t.match(
    /^(?:(?:hal|jarvis|assistant)[,:\s]+|please\s+)*(?:go(?:\s*to)?|goto|show(?:\s*me)?|open|take me to|switch to|navigate to|jump to|bring up|pull up)\s+(?:the\s+)?(.+)$/,
  )
  if (m) target = m[1]
  else {
    const b = t.match(/^(?:the\s+)?(.+?)\s+(?:page|tab|section|view|screen)$/)
    if (b) target = b[1]
  }
  if (!target) return null
  const q = target
    .replace(/\s+(page|tab|section|view|screen)$/, '')
    .replace(/[^a-z0-9+ ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (q.length < 2) return null
  const cands = Array.from(document.querySelectorAll<HTMLAnchorElement>('a[href^="/"]'))
    .map((a) => ({
      label: (a.textContent || '').toLowerCase().replace(/[^a-z0-9+ ]/g, ' ').replace(/\s+/g, ' ').trim(),
      path: a.getAttribute('href') || '',
    }))
    .filter((c) => c.label && c.path && !/^\/providers\/\d/.test(c.path))
  const pick = (pred: (l: string) => boolean) => cands.find((c) => pred(c.label)) || null
  const hit =
    pick((l) => l === q) ||
    pick((l) => l.indexOf(q) === 0) ||
    pick((l) => q.indexOf(l + ' ') === 0) ||
    pick((l) => l.split(' ').indexOf(q) > -1)
  return hit ? { path: hit.path, label: hit.label } : null
}

const SUGGESTIONS = [
  'Who are the 5 riskiest providers right now, and why?',
  'What CPT code is hemodialysis?',
  'Explain the OIG-exclusion signal.',
]

const VOICE_KEY = 'mfi-hal-voice' // persisted VOICE ON/OFF preference
const FACE_KEY = 'mfi-hal-face' // persisted active persona

// House rule: every HAL surface carries the face switcher — same transcript,
// same tools, only the persona/voice changes (mirrors qcode's AssistantWindow).
export type Face = 'assistant' | 'hal' | 'jarvis'
const FACES: Record<
  Face,
  { name: string; dot: string; tint?: string; voicePref: string[]; rate: number; pitch: number }
> = {
  assistant: {
    name: 'ASSISTANT',
    dot: '#9aa4b2',
    tint: 'saturate(0.15) brightness(1.15)',
    voicePref: ['Microsoft Aria Online (Natural) - English (United States)', 'Google US English'],
    rate: 1.0,
    pitch: 1.0,
  },
  hal: {
    name: 'HAL 9000',
    dot: '#ff4020',
    voicePref: [
      'Microsoft Guy Online (Natural) - English (United States)',
      'Microsoft Davis Online (Natural) - English (United States)',
      'Microsoft David - English (United States)',
      'Microsoft Mark - English (United States)',
      'Google US English',
      'Daniel',
      'Alex',
    ],
    rate: 0.82,
    pitch: 0.85,
  },
  jarvis: {
    name: 'J.A.R.V.I.S.',
    dot: '#37a4ff',
    tint: 'hue-rotate(215deg) saturate(1.15)',
    voicePref: [
      'Microsoft Ryan Online (Natural) - English (United Kingdom)',
      'Microsoft George - English (United Kingdom)',
      'Google UK English Male',
      'Daniel',
    ],
    rate: 0.98,
    pitch: 1.02,
  },
}

// The lens — red radial eye by default, tinted per persona.
function HalEye({
  size,
  state,
  tint,
}: {
  size: number
  state: 'idle' | 'thinking' | 'speaking'
  tint?: string
}) {
  return (
    <span
      className={`hal-lens hal-${state}`}
      style={{ width: size, height: size, filter: tint }}
      aria-hidden="true"
    >
      <span className="hal-glint" />
    </span>
  )
}

// Lifted out of HalPanel (mirrors useSidebarCollapsed in Sidebar.tsx) so the
// app shell can read/drive "open" too — it needs to know when HAL is open to
// push main content left instead of letting the panel cover it. Not persisted
// to localStorage: HAL should always start closed on a fresh page load.
export function useHalOpen() {
  const [open, setOpen] = useState(false)
  return { open, setOpen }
}

export default function HalPanel({
  open,
  setOpen,
}: {
  open: boolean
  setOpen: Dispatch<SetStateAction<boolean>>
}) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [listening, setListening] = useState(false)
  const [voiceOn, setVoiceOn] = useState(() => localStorage.getItem(VOICE_KEY) !== 'off')
  const [face, setFace] = useState<Face>(() => {
    const f = localStorage.getItem(FACE_KEY)
    return f === 'assistant' || f === 'jarvis' ? f : 'hal'
  })
  const faceRef = useRef<Face>(face)
  faceRef.current = face
  const pickFace = (f: Face) => {
    window.speechSynthesis?.cancel()
    setFace(f)
    try {
      localStorage.setItem(FACE_KEY, f)
    } catch {
      /* private mode */
    }
  }
  const [canListen, setCanListen] = useState(false)
  // Deploy gate: only render when the backend has a HAL relay configured
  // (HAL_TOKEN set). On prod — where qcode/HAL isn't reachable — the whole
  // panel stays hidden instead of showing a button that can only error.
  const [configured, setConfigured] = useState(false)
  const npi = useCurrentNpi()
  const navigate = useNavigate()

  useEffect(() => {
    api
      .halStatus()
      .then((r) => setConfigured(r.configured))
      .catch(() => setConfigured(false))
  }, [])

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

    const persona = FACES[faceRef.current]
    const utt = new SpeechSynthesisUtterance(text)
    utt.lang = faceRef.current === 'jarvis' ? 'en-GB' : 'en-US'
    // HAL: soft, unhurried. JARVIS: brisk, British. Assistant: neutral.
    utt.rate = persona.rate
    utt.pitch = persona.pitch
    utt.volume = 1

    // Best-effort voice pick — never block on voiceschanged (Chrome can
    // transiently return an empty list and never re-fire the event).
    const voices = synth.getVoices()
    const pick =
      persona.voicePref.map((n) => voices.find((v) => v.name === n)).find(Boolean) ??
      voices.find((v) => v.lang === utt.lang) ??
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
      // Client-side navigation: "go to the Network page", "open providers", etc.
      // HAL drives React Router itself instead of relaying to the backend (which
      // can't move the browser). Anything else falls through to HAL's brain.
      const route = halFindRoute(trimmed)
      if (route) {
        const name = route.label.replace(/\b\w/g, (c) => c.toUpperCase())
        const who = FACES[faceRef.current].name
        const line =
          who === 'J.A.R.V.I.S.'
            ? `Right away, sir — ${name}.`
            : who === 'HAL 9000'
              ? `Certainly, Dave. Bringing up ${name}.`
              : `Opening ${name}.`
        setMessages([...next, { role: 'assistant', content: line }])
        speak(line)
        navigate(route.path)
        return
      }
      setBusy(true)
      try {
        const res = await api.halChat(
          next.map((m) => ({ role: m.role, content: m.content })),
          npi ?? undefined,
          faceRef.current,
        )
        const reply = res.reply || '(no reply)'
        setMessages((m) => [...m, { role: 'assistant', content: reply, actions: res.actions, providers: res.providers }])
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
    [busy, messages, npi, speak, navigate],
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
    rec.onerror = (e) => {
      setListening(false)
      const why = MIC_ERRORS[e?.error ?? '']
      if (why) {
        setMessages((m) => [...m, { role: 'assistant', content: why, error: true }])
      }
    }
    recRef.current = rec
    setListening(true)
    try {
      rec.start()
    } catch {
      setListening(false)
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: 'The microphone could not be started in this window.', error: true },
      ])
    }
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

  if (!configured) return null

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
            {/* Header — the eye, name, live status, face switcher */}
            <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
              <HalEye size={34} state={eyeState} tint={FACES[face].tint} />
              <div className="flex-1">
                <div className="text-sm font-bold uppercase tracking-[0.3em] text-ink-primary">
                  {FACES[face].name}
                </div>
                <div className="text-[10px] uppercase tracking-[0.25em] text-ink-tertiary">{status}</div>
              </div>
              {/* Face switcher — same transcript, same tools, different persona */}
              <div className="flex items-center gap-1.5" role="group" aria-label="Choose persona">
                {(Object.keys(FACES) as Face[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => pickFace(f)}
                    title={FACES[f].name}
                    aria-label={`Talk to ${FACES[f].name}`}
                    aria-pressed={face === f}
                    className="rounded-full p-0.5 transition-transform hover:scale-125"
                    style={{
                      outline: face === f ? `1px solid ${FACES[f].dot}` : 'none',
                      outlineOffset: 2,
                    }}
                  >
                    <span
                      className="block h-2.5 w-2.5 rounded-full"
                      style={{ background: FACES[f].dot, opacity: face === f ? 1 : 0.45 }}
                    />
                  </button>
                ))}
              </div>
              {messages.some((m) => m.role === 'assistant') && (
                <button
                  onClick={() => buildReportSlideshow(messages)}
                  className="text-[10px] uppercase tracking-wider text-threat-critical hover:text-threat-high transition-colors"
                  title="Turn this conversation into a slideshow report"
                >
                  Report
                </button>
              )}
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
                      {m.role === 'assistant' ? (
                        <LinkifiedText text={m.content} providers={m.providers} />
                      ) : (
                        <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                      )}
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
