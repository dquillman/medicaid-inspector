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
  // External link rendered under the message text (e.g. the YouTube tab HAL
  // just opened — kept clickable in case the popup was blocked or closed).
  href?: { url: string; label: string }
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

// Chrome hard-blocks mic/speech on an insecure origin: only https://, or
// localhost / 127.0.0.1, count as a "secure context". A LAN IP or machine
// name over http:// can never be granted, so say so plainly rather than
// pointing at Site settings (which won't help).
const INSECURE_MIC_MSG =
  'The microphone is blocked because this page is on an insecure origin ' +
  `(${typeof window !== 'undefined' ? window.location.origin : ''}). ` +
  'Chrome only allows mic access over https:// or via localhost / 127.0.0.1. ' +
  'Open the app at http://localhost:<port> or the https:// deployed site, then try again.'

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

// DJ mode: parse a play-music command ("play music", "play some 70s music",
// "put on 80s tunes") and resolve it to a YouTube target. Client-side for the
// same reason as halFindRoute — the backend can't open a browser tab. The
// default (no decade/genre given) is a verified 70s greatest-hits compilation
// with YouTube's radio list chained after it so the music keeps going; any
// explicit qualifier falls back to a YouTube search for that era/genre.
const MUSIC_70S_URL =
  'https://www.youtube.com/watch?v=WanZkMp31xw&list=RDWanZkMp31xw&start_radio=1'
const MUSIC_DECADES: Record<string, string> = {
  fifties: '50s', sixties: '60s', seventies: '70s', eighties: '80s', nineties: '90s',
}
function halFindMusic(text: string): { url: string; label: string } | null {
  const t = text.toLowerCase().trim().replace(/[.!?]+$/, '')
  const m = t.match(
    /^(?:(?:hal|jarvis|assistant)[,:\s]+|please\s+)*(?:play|put on|spin up|spin)\s+(?:me\s+)?(?:some\s+|a little\s+|the\s+)?(.*?)\s*(?:music|tunes|songs|hits)(?:\s+please)?$/,
  )
  if (!m) return null
  let q = (m[1] || '').replace(/\s+/g, ' ').trim()
  q = MUSIC_DECADES[q] || q
  if (!q || q === '70s') return { url: MUSIC_70S_URL, label: '70s greatest hits' }
  return {
    url: `https://www.youtube.com/results?search_query=${encodeURIComponent(`${q} greatest hits playlist`)}`,
    label: `${q} music`,
  }
}

const SUGGESTIONS = [
  'Who are the 5 riskiest providers right now, and why?',
  'What CPT code is hemodialysis?',
  'Explain the OIG-exclusion signal.',
  'Play some 70s music.',
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

// The eye — per persona: HAL's red radial lens, JARVIS's blue arc reactor
// (same design as the qcode ops JARVIS console), assistant's neutral/tinted lens.
function HalEye({
  size,
  state,
  tint,
  face,
  bezel,
}: {
  size: number
  state: 'idle' | 'thinking' | 'speaking'
  tint?: string
  face?: Face
  // When true, the HAL/assistant lens is set in a metallic bezel ring (the qcode
  // console plate look). Omit for the small floating toggle eye.
  bezel?: boolean
}) {
  if (face === 'jarvis') {
    const inset = Math.max(2, Math.round(size * 0.09))
    const core = Math.round(size * 0.46)
    return (
      <span className={`hal-reactor hal-${state}`} style={{ width: size, height: size }} aria-hidden="true">
        <span className="hal-coils" style={{ inset }} />
        <span className="hal-core" style={{ width: core, height: core }} />
      </span>
    )
  }
  const lensSize = bezel ? Math.round(size * 0.61) : size
  const steel = face === 'assistant'
  const lens = (
    <span
      className={`hal-lens hal-${state}${steel ? ' hal-steel' : ''}`}
      style={{ width: lensSize, height: lensSize, filter: steel ? undefined : tint }}
      aria-hidden="true"
    >
      <span className="hal-glint" />
    </span>
  )
  if (!bezel) return lens
  const pad = Math.max(3, Math.round(size * 0.08))
  return (
    <span className="hal-ring" style={{ width: size, height: size, padding: pad }} aria-hidden="true">
      <span className="hal-bezel">{lens}</span>
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
  const [paused, setPaused] = useState(false)
  const [listening, setListening] = useState(false)
  // LIVE (hands-free) conversation mode — see HAL_SPEC §3b.
  const [live, setLive] = useState(false)
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
  // Refs mirror state for the LIVE loop and speak()'s finish handler.
  const liveRef = useRef(live)
  liveRef.current = live
  const busyRef = useRef(busy)
  busyRef.current = busy
  const listeningRef = useRef(listening)
  listeningRef.current = listening
  const listenRef = useRef<() => void>(() => {})
  // True while the USER has paused speech. The keep-alive interval below must
  // not fight this (its pause/resume would otherwise instantly un-pause us).
  const userPausedRef = useRef(false)

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
    // A new utterance always starts un-paused.
    userPausedRef.current = false
    setPaused(false)

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
      // Don't fight a deliberate user pause — only nudge Chrome when playing.
      if (userPausedRef.current) return
      synth.pause()
      synth.resume()
    }, 10000)
    const finish = () => {
      if (keepAlive) {
        clearInterval(keepAlive)
        keepAlive = null
      }
      userPausedRef.current = false
      setPaused(false)
      setSpeaking(false)
      // LIVE (hands-free): re-open the ears ~700ms after HAL finishes.
      if (liveRef.current)
        setTimeout(() => {
          if (liveRef.current && !busyRef.current && !window.speechSynthesis?.speaking && !listeningRef.current)
            listenRef.current()
        }, 700)
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
      // DJ mode: "play music" (default: 70s greatest hits), "play 80s music",
      // etc. Opens YouTube in a new tab. Must run before any await so the
      // window.open still carries the user gesture (popup blockers). Voice-
      // initiated sends may lack that gesture — the chat link is the fallback.
      const music = halFindMusic(trimmed)
      if (music) {
        const who = FACES[faceRef.current].name
        const line =
          who === 'J.A.R.V.I.S.'
            ? `With pleasure, sir — ${music.label}, on YouTube.`
            : who === 'HAL 9000'
              ? `Certainly, Dave. ${music.label}. I know how much you enjoy this era.`
              : `Playing ${music.label} on YouTube.`
        const win = window.open(music.url, '_blank', 'noopener')
        window.focus() // return focus to this tab — the new tab shouldn't steal it
        setMessages([
          ...next,
          {
            role: 'assistant',
            content: win ? line : `${line} Your browser blocked the new tab — use the link below.`,
            href: { url: music.url, label: `▶ ${music.label} on YouTube` },
          },
        ])
        speak(line)
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
  // Set once getUserMedia has granted the mic this session, so the hands-free
  // re-arm loop skips the permission round-trip and starts instantly.
  const micGrantedRef = useRef(false)

  const listen = useCallback(() => {
    if (!canListen || listening || busy) return

    // Actually spin up SpeechRecognition. Only reached once the mic is known
    // to be permitted (fast path) or freshly granted below.
    const startRec = () => {
    window.speechSynthesis?.cancel() // don't listen to ourselves
    const w = window as unknown as Record<string, unknown>
    const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as new () => Recognition
    const rec = new Ctor()
    rec.lang = 'en-US'
    rec.continuous = false
    rec.interimResults = false
    let gotResult = false
    rec.onresult = (e) => {
      const t = e.results[0]?.[0]?.transcript ?? ''
      if (t) {
        gotResult = true
        void send(t)
      }
    }
    rec.onend = () => {
      setListening(false)
      recRef.current = null
      // LIVE: keep the ears open after silence; a result re-arms via speak()→finish.
      if (liveRef.current && !gotResult)
        setTimeout(() => {
          if (liveRef.current && !busyRef.current && !window.speechSynthesis?.speaking && !listeningRef.current)
            listenRef.current()
        }, 300)
    }
    rec.onerror = (e) => {
      setListening(false)
      const code = e?.error ?? ''
      // Permission/hardware failures are fatal to hands-free mode - leave LIVE.
      if (code === 'not-allowed' || code === 'service-not-allowed' || code === 'audio-capture') setLive(false)
      const why = MIC_ERRORS[code]
      // Suppress the chatty "no-speech" notice while hands-free (onend re-arms).
      if (why && !(liveRef.current && code === 'no-speech')) {
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
    }

    // Fast path: mic already granted this session — start immediately.
    if (micGrantedRef.current) return startRec()

    // Insecure origin: the browser will never grant the mic here. Say exactly
    // why instead of failing with the generic "blocked" notice.
    if (!window.isSecureContext) {
      setLive(false)
      setMessages((m) => [...m, { role: 'assistant', content: INSECURE_MIC_MSG, error: true }])
      return
    }

    // Explicitly request the mic so Chrome shows the real Allow/Block prompt —
    // SpeechRecognition alone stays silent when the permission is in "ask"
    // limbo and just errors with not-allowed. Release the stream right away;
    // recognition opens its own capture.
    const md = navigator.mediaDevices
    if (!md?.getUserMedia) return startRec() // ancient browser — let rec try
    md.getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach((t) => t.stop())
        micGrantedRef.current = true
        startRec()
      })
      .catch(() => {
        setListening(false)
        setLive(false)
        setMessages((m) => [...m, { role: 'assistant', content: MIC_ERRORS['not-allowed'], error: true }])
      })
  }, [canListen, listening, busy, send])
  useEffect(() => {
    listenRef.current = listen
  }, [listen])

  // MIC = barge-in: cut HAL off mid-sentence and listen now (or stop if listening).
  const micClick = useCallback(() => {
    window.speechSynthesis?.cancel()
    userPausedRef.current = false
    setPaused(false)
    setSpeaking(false)
    if (listeningRef.current) {
      recRef.current?.stop()
      return
    }
    listen()
  }, [listen])

  // LIVE = hands-free conversation loop (echo-safe: mic off while HAL speaks).
  const toggleLive = useCallback(() => {
    setLive((v) => {
      const next = !v
      if (next) setTimeout(() => listenRef.current(), 0)
      else recRef.current?.stop()
      return next
    })
  }, [])

  // ---- Pause / resume the current spoken reply ------------------------------
  const togglePause = useCallback(() => {
    const synth = window.speechSynthesis
    if (!synth || !synth.speaking) return
    if (userPausedRef.current) {
      synth.resume()
      userPausedRef.current = false
      setPaused(false)
    } else {
      synth.pause()
      userPausedRef.current = true
      setPaused(true)
    }
  }, [])

  // Stop audio when the panel closes or unmounts.
  useEffect(() => {
    if (!open) {
      liveRef.current = false // stop the LIVE loop when the panel is closed
      setLive(false)
      window.speechSynthesis?.cancel()
      recRef.current?.stop()
      userPausedRef.current = false
      setPaused(false)
      setSpeaking(false)
    }
  }, [open])
  useEffect(
    () => () => {
      liveRef.current = false // stop any pending LIVE re-arm after unmount
      window.speechSynthesis?.cancel()
      recRef.current?.stop()
    },
    [],
  )

  const eyeState: 'idle' | 'thinking' | 'speaking' = speaking ? 'speaking' : busy ? 'thinking' : 'idle'
  // Idle status word matches the qcode consoles per persona: JARVIS reads ONLINE.
  const idleStatus = face === 'jarvis' ? 'ONLINE' : 'OPERATIONAL'
  const status = listening ? 'LISTENING' : speaking ? 'SPEAKING' : busy ? 'PROCESSING' : idleStatus

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
        /* Assistant: a neutral STEEL lens (its own identity, not a dimmed HAL eye). */
        .hal-lens.hal-steel {
          background: radial-gradient(circle at 50% 44%,
            #fff 0%, #eef2f8 6%, #c2ccda 20%, #8a97a9 42%, #444e5c 66%, #1a1f27 84%, #000 96%);
          box-shadow: 0 0 18px 4px rgba(150,175,210,.5);
        }
        /* Metallic bezel ring for the plate eye (qcode console design). */
        .hal-ring {
          border-radius: 9999px; box-sizing: border-box;
          background: linear-gradient(155deg, #ececec, #8f8f8f 30%, #3c3c3c 62%, #a8a8a8);
          box-shadow: 0 0 14px rgba(0,0,0,.95), inset 0 0 6px rgba(0,0,0,.65);
        }
        .hal-bezel {
          position: relative; width: 100%; height: 100%; border-radius: 9999px; background: #050505;
          display: flex; align-items: center; justify-content: center; box-shadow: inset 0 0 12px #000;
        }
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
        /* JARVIS arc reactor — housing → rotating segmented coil ring → blue core. */
        .hal-reactor {
          position: relative; display: inline-flex; align-items: center; justify-content: center;
          border-radius: 9999px; flex: none;
          background: radial-gradient(circle, #0b1420 55%, #1a2836 72%, #0a0e14 100%);
          box-shadow: 0 0 12px rgba(60,180,255,.3), inset 0 0 8px #000;
        }
        .hal-coils {
          position: absolute; border-radius: 9999px;
          background: repeating-conic-gradient(from 0deg,
            rgba(120,220,255,.9) 0deg 12deg, rgba(10,20,30,.05) 12deg 36deg);
          -webkit-mask: radial-gradient(circle, transparent 54%, #000 58%, #000 86%, transparent 90%);
          mask: radial-gradient(circle, transparent 54%, #000 58%, #000 86%, transparent 90%);
          animation: jvIdle 24s linear infinite; filter: drop-shadow(0 0 4px rgba(90,200,255,.6));
        }
        .hal-core {
          border-radius: 9999px;
          background: radial-gradient(circle at 50% 48%,
            #fff 0%, #dff6ff 22%, #8fdcff 44%, #37a8e8 66%, #0c3a5e 86%, #051524 100%);
          box-shadow: 0 0 12px 3px rgba(90,200,255,.6); animation: jvBreathe 4.5s ease-in-out infinite;
        }
        .hal-reactor.hal-thinking .hal-coils { animation: jvIdle 2.2s linear infinite; }
        .hal-reactor.hal-speaking .hal-core { animation: jvSpeak .5s ease-in-out infinite; }
        @keyframes jvIdle { to { transform: rotate(360deg); } }
        @keyframes jvBreathe {
          0%, 100% { filter: brightness(.9); }
          50% { filter: brightness(1.15); }
        }
        @keyframes jvSpeak {
          0%, 100% { filter: brightness(.95); box-shadow: 0 0 12px 3px rgba(90,200,255,.5); }
          50% { filter: brightness(1.4); box-shadow: 0 0 22px 6px rgba(140,225,255,.9); }
        }
        /* Console plate + chrome — the qcode ops console design language. */
        .hal-console { background: #05060a; color: #cfd6e4;
          font-family: "Bahnschrift", "Arial Narrow", Arial, sans-serif; }
        .hal-plate {
          position: relative; display: flex; flex-direction: column; align-items: center; gap: 8px;
          padding: 22px 12px 14px; border-bottom: 1px solid #16181d;
        }
        .hal-plate-actions { position: absolute; top: 10px; right: 12px; display: flex; gap: 14px; align-items: center; }
        .hal-console-link {
          background: none; border: none; cursor: pointer; padding: 0;
          font: 11px "Bahnschrift", "Arial Narrow", Arial, sans-serif; letter-spacing: .12em;
          text-transform: uppercase; color: #6b7480; line-height: 1;
        }
        .hal-console-link:hover { color: #ff6a4a; }
        .hal-console-name { letter-spacing: .45em; font-size: 15px; padding-left: .45em; }
        .hal-console-status { letter-spacing: .3em; font-size: 10px; color: #5a6578; text-transform: uppercase; }
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
            className="hal-console no-print fixed top-12 right-0 z-40 flex h-[calc(100%-3rem)] w-full sm:max-w-md flex-col border-l border-hairline elev-3"
            role="dialog"
            aria-label="HAL assistant"
          >
            {/* Header — centered eye PLATE (qcode ops console design), with the
                Report/Clear/Close actions floated top-right. */}
            <div className="hal-plate">
              <div className="hal-plate-actions">
                {messages.some((m) => m.role === 'assistant') && (
                  <button
                    onClick={() => buildReportSlideshow(messages)}
                    className="hal-console-link"
                    title="Turn this conversation into a slideshow report"
                  >
                    Report
                  </button>
                )}
                {messages.length > 0 && (
                  <button
                    onClick={() => setMessages([])}
                    className="hal-console-link"
                    title="Clear conversation"
                  >
                    Clear
                  </button>
                )}
                <button onClick={() => setOpen(false)} className="hal-console-link" aria-label="Close HAL" title="Close">
                  ✕
                </button>
              </div>
              <HalEye size={72} state={eyeState} tint={FACES[face].tint} face={face} bezel />
              <div
                className="hal-console-name"
                style={{ color: face === 'jarvis' ? '#ffd47e' : face === 'assistant' ? '#b8c4d4' : '#9db4ff' }}
              >
                {FACES[face].name}
              </div>
              <div className="hal-console-status">{status}</div>
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
                      {m.href && (
                        <a
                          href={m.href.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1.5 inline-block rounded border border-hairline bg-surface-0/60 px-2 py-1 text-xs font-medium text-brand-400 hover:text-brand-300 hover:border-brand-400/40 transition-colors"
                        >
                          {m.href.label}
                        </a>
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
                  <>
                    <button
                      onClick={micClick}
                      className={`mb-0.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
                        listening
                          ? 'border-threat-critical text-threat-critical shadow-[0_0_12px_rgba(215,38,61,0.4)]'
                          : 'border-hairline text-ink-tertiary hover:border-threat-critical/50 hover:text-ink-secondary'
                      }`}
                      title="Talk to HAL — tap to cut in mid-reply and speak"
                      aria-label="Voice input"
                    >
                      {listening ? '● Mic' : 'Mic'}
                    </button>
                    <button
                      onClick={toggleLive}
                      className={`mb-0.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
                        live
                          ? 'border-threat-critical text-threat-critical shadow-[0_0_12px_rgba(215,38,61,0.4)]'
                          : 'border-hairline text-ink-tertiary hover:border-threat-critical/50 hover:text-ink-secondary'
                      }`}
                      title="Hands-free conversation — HAL listens, replies, then listens again. Tap Mic to cut in."
                      aria-label="Hands-free conversation mode"
                    >
                      {live ? '◉ Live' : 'Live'}
                    </button>
                  </>
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
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={togglePause}
                  disabled={!speaking}
                  className="flex-1 rounded-lg border border-hairline px-3 py-2 text-sm font-semibold uppercase tracking-wider text-ink-secondary transition-colors hover:border-threat-critical/50 hover:text-ink-primary disabled:opacity-30 disabled:hover:border-hairline disabled:hover:text-ink-secondary"
                  title={paused ? 'Resume HAL’s speech' : 'Pause HAL’s speech'}
                  aria-label={paused ? 'Resume speech' : 'Pause speech'}
                >
                  {paused ? '► Resume' : '❚❚ Pause'}
                </button>
                <button
                  onClick={() => {
                    // Muting stops any in-flight speech immediately; unmuting
                    // just re-enables it for the next reply.
                    window.speechSynthesis?.cancel()
                    userPausedRef.current = false
                    setPaused(false)
                    setSpeaking(false)
                    setVoiceOn((v) => {
                      localStorage.setItem(VOICE_KEY, v ? 'off' : 'on')
                      return !v
                    })
                  }}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold uppercase tracking-wider transition-colors ${
                    voiceOn
                      ? 'border-hairline text-ink-secondary hover:border-threat-critical/50 hover:text-ink-primary'
                      : 'border-threat-critical text-threat-critical hover:text-threat-critical/80'
                  }`}
                  title={voiceOn ? 'Mute HAL’s voice' : 'Unmute HAL’s voice'}
                  aria-label={voiceOn ? 'Mute voice' : 'Unmute voice'}
                >
                  {voiceOn ? '🔊 Mute' : '🔇 Muted'}
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
      className="h-1.5 w-1.5 rounded-full bg-threat-critical"
      animate={{ opacity: [0.3, 1, 0.3] }}
      transition={{ duration: 1, repeat: Infinity, delay }}
    />
  )
}
