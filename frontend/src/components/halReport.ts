// Turn a HAL conversation into a slideshow report. Builds a self-contained
// reveal.js deck (CDN) in a Blob and opens it in a new tab — no backend, no
// build step. Provider names link to their /providers/<npi> pages, and the
// deck offers a one-click "copy for NotebookLM" so Dave can drop the same
// source into NotebookLM for an audio/notebook version.
import type { HalProvider } from '../lib/api'

export type ReportMsg = {
  role: 'user' | 'assistant'
  content: string
  providers?: HalProvider[]
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

function linkify(text: string, providers: HalProvider[], origin: string): string {
  let html = escapeHtml(text)
  const uniq = Array.from(new Map(providers.map((p) => [p.name.toLowerCase(), p])).values())
    .filter((p) => p.name && p.name.length >= 3)
    .sort((a, b) => b.name.length - a.name.length)
  for (const p of uniq) {
    const rx = new RegExp(`(${p.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
    html = html.replace(
      rx,
      `<a href="${origin}/providers/${p.npi}" target="_blank" rel="noopener">$1</a>`,
    )
  }
  return html.replace(/\n/g, '<br>')
}

// Split one assistant answer into slides: a lead slide plus one slide per
// numbered item (e.g. "1. …", "2. …"), which is exactly how the risk lists read.
function answerToSlides(
  question: string,
  answer: string,
  providers: HalProvider[],
  origin: string,
): string[] {
  const lines = answer.split('\n')
  const preamble: string[] = []
  const items: string[][] = []
  let cur: string[] | null = null
  for (const line of lines) {
    if (/^\s*\d+[.)]\s/.test(line)) {
      if (cur) items.push(cur)
      cur = [line]
    } else if (cur) {
      cur.push(line)
    } else {
      preamble.push(line)
    }
  }
  if (cur) items.push(cur)

  const q = escapeHtml(question || 'HAL')
  const slides: string[] = []
  if (items.length === 0) {
    slides.push(
      `<section><h3>${q}</h3><p class="body">${linkify(answer, providers, origin)}</p></section>`,
    )
    return slides
  }
  const lead = preamble.join('\n').trim()
  slides.push(
    `<section><h2>${q}</h2>${lead ? `<p class="body">${linkify(lead, providers, origin)}</p>` : ''}` +
      `<p class="muted">${items.length} items</p></section>`,
  )
  for (const item of items) {
    const raw = item.join('\n').trim()
    const num = (raw.match(/^\s*(\d+)/) || [])[1] || ''
    slides.push(
      `<section><div class="num">${num}</div>` +
        `<p class="body">${linkify(raw.replace(/^\s*\d+[.)]\s*/, ''), providers, origin)}</p></section>`,
    )
  }
  return slides
}

export function buildReportSlideshow(messages: ReportMsg[]): void {
  const origin = window.location.origin
  const pairs: string[] = []
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]
    if (m.role !== 'assistant') continue
    const q = i > 0 && messages[i - 1].role === 'user' ? messages[i - 1].content : ''
    pairs.push(...answerToSlides(q, m.content, m.providers || [], origin))
  }
  if (pairs.length === 0) {
    alert('Ask HAL something first — then Report turns the answer into a slideshow.')
    return
  }
  const notebookSource = messages
    .map((m) => `${m.role === 'user' ? 'Q' : 'HAL'}: ${m.content}`)
    .join('\n\n')
    .replace(/<\/script>/gi, '<\\/script>')

  const title = 'Medicaid Inspector — HAL Report'
  const cover =
    `<section data-background-color="#0b0f14"><h1>${title}</h1>` +
    `<p class="muted">Generated from the Ask HAL conversation</p>` +
    `<button class="nlm" onclick="copyNLM()">Copy source for NotebookLM</button> ` +
    `<a class="nlm" href="https://notebooklm.google.com/" target="_blank" rel="noopener">Open NotebookLM</a></section>`

  const R = 'https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.6.1'
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<link rel="stylesheet" href="${R}/reveal.min.css">
<link rel="stylesheet" href="${R}/theme/black.min.css">
<style>
.reveal h1{font-size:1.8em} .reveal h2{font-size:1.3em;color:#f0997b}
.reveal h3{font-size:1.1em;color:#f0997b}
.reveal .body{font-size:0.7em;line-height:1.5;text-align:left}
.reveal .muted{color:#8a97a8;font-size:0.6em}
.reveal .num{font-size:2.6em;color:#e24b4a;font-weight:700;line-height:1}
.reveal a{color:#5dcaa5}
.nlm{display:inline-block;margin-top:1rem;font-size:0.5em;padding:.4em .8em;
  border:1px solid #5dcaa5;border-radius:6px;color:#5dcaa5;cursor:pointer;background:none}
</style></head><body>
<div class="reveal"><div class="slides">${cover}${pairs.join('')}</div></div>
<script src="${R}/reveal.min.js"></script>
<script>
var NLM=${JSON.stringify(notebookSource)};
function copyNLM(){navigator.clipboard.writeText(NLM).then(function(){alert('Report source copied — paste it into a NotebookLM source.');});}
Reveal.initialize({hash:true,slideNumber:'c/t'});
</script></body></html>`

  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
