/**
 * Bake the Landing hero "Constellation" point cloud from the real scan data.
 *
 * backend/prescan_slim.json is ~60 MB — it must NEVER be shipped or fetched by
 * the browser. This build-time script samples ~6,000 providers down to a tiny
 * Float32Array (x, y, z, risk, seed per point ≈ 120 KB) written to
 * frontend/public/constellation.bin, which the hero fetches lazily.
 *
 * Re-run after a data refresh:  node scripts/bake-constellation.mjs
 * (run from the frontend/ dir). Commit the resulting public/constellation.bin.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(SCRIPT_DIR, '..')
const SLIM = path.resolve(FRONTEND, '..', 'backend', 'prescan_slim.json')
const OUT = path.resolve(FRONTEND, 'public', 'constellation.bin')

const COUNT = 6000
const STRIDE = 5 // x, y, z, risk, seed

function main() {
  if (!fs.existsSync(SLIM)) {
    console.error(`[bake] prescan_slim.json not found at ${SLIM} — run a scan / pull the cache first.`)
    process.exit(1)
  }
  console.log('[bake] reading slim cache…')
  const raw = JSON.parse(fs.readFileSync(SLIM, 'utf8'))
  const providers = Array.isArray(raw) ? raw : raw.providers || []
  console.log(`[bake] ${providers.length.toLocaleString()} providers`)

  // Even sample across the (total_paid-sorted) cache so the field spans the
  // whole population, not just the top.
  const step = Math.max(1, Math.floor(providers.length / COUNT))
  const sample = []
  for (let i = 0; i < providers.length && sample.length < COUNT; i += step) {
    sample.push(providers[i])
  }
  const n = sample.length
  const arr = new Float32Array(n * STRIDE)

  for (let k = 0; k < n; k++) {
    const p = sample[k]
    const risk = Math.min(1, Math.max(0, (Number(p?.risk_score) || 0) / 100))
    // galactic disc: sqrt-radius for uniform area density, gentle 2-turn spiral.
    const r = Math.sqrt(Math.random())
    const theta = Math.random() * Math.PI * 2 + r * 3.0
    // pull the hottest providers slightly toward the lit core
    const rr = r * (1 - risk * 0.25)
    const x = Math.cos(theta) * rr
    const z = Math.sin(theta) * rr
    const y = (Math.random() - 0.5) * 0.14 * (1 - rr * 0.4) // thin disc
    const seed = Math.random()
    const o = k * STRIDE
    arr[o] = x
    arr[o + 1] = y
    arr[o + 2] = z
    arr[o + 3] = risk
    arr[o + 4] = seed
  }

  fs.mkdirSync(path.dirname(OUT), { recursive: true })
  fs.writeFileSync(OUT, Buffer.from(arr.buffer))
  console.log(`[bake] wrote ${n.toLocaleString()} points → ${path.relative(FRONTEND, OUT)} (${(arr.byteLength / 1024).toFixed(0)} KB)`)
}

main()
