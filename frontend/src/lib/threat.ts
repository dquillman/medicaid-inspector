/**
 * The single source of UI "temperature" across NOCTURNE.
 *
 * Risk is the only thing allowed to break the monochrome — and it does so on a
 * continuous cold→arterial ramp, not five hard buckets. Tables, score bars,
 * the cytoscape graph, KPIs and the Fraud Brain all color through here so the
 * whole app agrees on what a given score "feels" like.
 *
 * 508 note: these colors are for FILLS / BARS / DOTS / BORDERS only (>=3:1
 * graphical threshold). Never use them for small text or 1px ticks, and always
 * pair risk color with the <Magnitude> glyph so meaning never depends on hue.
 */

type RGB = [number, number, number]

// Anchors evenly spaced 0..100 → matches the 5 tailwind threat stops.
const STOPS: { at: number; rgb: RGB }[] = [
  { at: 0,   rgb: [0x3f, 0xbf, 0x8f] }, // clear
  { at: 25,  rgb: [0x7f, 0xb0, 0x4a] }, // low
  { at: 50,  rgb: [0xe0, 0xa5, 0x3a] }, // medium
  { at: 75,  rgb: [0xe2, 0x60, 0x3a] }, // high
  { at: 100, rgb: [0xd7, 0x26, 0x3d] }, // critical
]

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n))
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

function ramp(score: number): RGB {
  const s = clamp(score, 0, 100)
  for (let i = 1; i < STOPS.length; i++) {
    const a = STOPS[i - 1]
    const b = STOPS[i]
    if (s <= b.at) {
      const t = (s - a.at) / (b.at - a.at)
      return [
        Math.round(lerp(a.rgb[0], b.rgb[0], t)),
        Math.round(lerp(a.rgb[1], b.rgb[1], t)),
        Math.round(lerp(a.rgb[2], b.rgb[2], t)),
      ]
    }
  }
  return STOPS[STOPS.length - 1].rgb
}

/** Continuous threat color for any 0–100 score, as `rgb(...)`. */
export function threatColor(score: number, alpha = 1): string {
  const [r, g, b] = ramp(score)
  return alpha >= 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Discrete band name (for labels / aria), aligned to the ramp. */
export function threatBand(score: number): 'CLEAR' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' {
  const s = clamp(score, 0, 100)
  if (s >= 80) return 'CRITICAL'
  if (s >= 60) return 'HIGH'
  if (s >= 40) return 'MEDIUM'
  if (s >= 20) return 'LOW'
  return 'CLEAR'
}

/** Colorblind-safe magnitude glyph — risk is never hue-only. */
const GLYPHS = ['○', '◔', '◑', '◕', '●'] as const // ○ ◔ ◑ ◕ ●
export function magnitudeGlyph(score: number): string {
  const i = clamp(Math.floor(clamp(score, 0, 100) / 20), 0, 4)
  return GLYPHS[i]
}
