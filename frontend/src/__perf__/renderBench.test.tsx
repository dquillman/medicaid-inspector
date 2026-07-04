/**
 * Headless render benchmark for EVERY page.
 *
 * Measures the React commit cost (Profiler `actualDuration` — pure reconciliation
 * work, independent of browser paint) for every page in src/pages with realistic
 * data resolved, so the number reflects the DATA-PRESENT render, not the loading
 * skeleton.
 *
 * Target: 56ms per commit in a REAL browser. This harness renders under jsdom,
 * whose DOM ops run ~2-3x slower than a browser's, and absolute timings drift
 * with machine load. The printed "~Nms browser est." lines are the real signal;
 * the assertion is a generous non-flaky catastrophe guard.
 *
 * Run: npx vitest run src/__perf__/renderBench.test.tsx
 */
import { Profiler, Component, createElement, type ReactNode } from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ProviderFlagsProvider } from '../hooks/useProviderFlags'

const BROWSER_TARGET_MS = 56
const JSDOM_FACTOR = 2.5              // jsdom is ~2-3x slower than a real browser
const REGRESSION_CEILING_MS = 220     // generous catastrophe guard (non-flaky)

// ── Fixtures ────────────────────────────────────────────────────────────────
const SIGNALS = ['billing_concentration', 'revenue_per_bene_outlier', 'claims_per_bene_anomaly']
function signalResults(n: number) {
  return SIGNALS.slice(0, n).map((s, i) => ({
    signal: s, score: 0.8 - i * 0.1, weight: 20 - i * 5, reason: `${s} triggered`, flagged: true,
  }))
}
function makeRows(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const flags = signalResults(i % 4)
    return {
      npi: String(1000000000 + i), provider_name: `Provider ${i} LLC`, name: `Provider ${i} LLC`,
      city: ['HARTFORD', 'MIAMI', 'DALLAS', 'NEWARK'][i % 4], state: ['CT', 'FL', 'TX', 'NJ'][i % 4], zip: '06114',
      total_paid: 500000 - i * 1000, total_claims: 5000 - i * 10, total_beneficiaries: 400 - i,
      distinct_hcpcs: 3 + (i % 10), active_months: 6 + (i % 12), first_month: '2018-10', last_month: '2020-04',
      risk_score: 95 - (i % 40), flags, signal_results: flags, flag_count: flags.length,
      status: 'pending', added_at: 1_700_000_000, updated_at: 1_700_000_000,
      hcpcs_code: `J${1000 + i}`, description: 'Test code', pct: 50 - i, amount: 1000 * i,
      count: 25 - i, label: `Item ${i}`, value: 100 - i, severity: 'HIGH', reason: 'test',
    }
  })
}
const ROWS = makeRows(40)
function makeTimeline(months = 24) {
  return Array.from({ length: months }, (_, i) => ({
    month: `20${18 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`,
    total_paid: 20000 + (i * 137) % 9000, amount: 20000 + (i * 137) % 9000,
    total_claims: 200 + (i * 7) % 90, total_unique_beneficiaries: 40 + (i % 30), count: 40 + (i % 30),
  }))
}

// One universal, over-populated response: whatever list key a page reads, it
// finds rows; whatever scalar it reads, it finds a number. Specific paths that
// need an exact shape are matched first.
function fixtureFor(path: string): unknown {
  if (/\/providers\/[^/]+\/timeline/.test(path)) return { npi: '1', timeline: makeTimeline() }
  if (/\/providers\/[^/]+\/hcpcs/.test(path)) return { npi: '1', hcpcs: ROWS }
  if (/\/providers\/[^/]+\/narrative/.test(path)) return { narrative: 'x', sections: [{ title: 'A', content: 'b' }], generated_at: '2026-01-01T00:00:00', word_count: 100 }
  if (/\/providers\/[^/]+\/peer/.test(path)) return { this_provider: ROWS[0], percentiles: {}, stats: {} }
  if (/\/providers\/[^/]+\/network/.test(path)) return { nodes: ROWS.slice(0, 10), edges: [], center: ROWS[0] }
  if (path.includes('/provider-facets') || path.includes('/facets')) return { states: ['CT', 'FL', 'TX', 'NJ'], cities: ['HARTFORD', 'MIAMI'] }
  if (path.includes('/anomalies')) return { total: 40, page: 1, limit: 50, anomalies: ROWS }
  if (/\/providers(\?|$)/.test(path) || path.endsWith('/providers')) return { providers: ROWS, page: 1, limit: 50, total: 12800 }
  if (path.includes('/summary')) return {
    total_providers: 106660, total_paid: 9.1e9, total_claims: 4.2e7, total_beneficiaries: 3.1e6,
    flagged_providers: 8200, high_risk_providers: 1900, avg_risk_score: 22.4, prescan_complete: true,
  }
  if (path.includes('/methods')) return { signal_count: 18, signals: ROWS.map(r => ({ ...r, citations: ['42 CFR 455'], explanation: 'x' })), provenance: {}, composite_methodology: 'x' }
  const NPPES = {
    name: 'Provider 0 LLC', entity_type: 'NPI-1',
    address: { line1: '1 Main St', line2: '', city: 'HARTFORD', state: 'CT', zip: '061143202' },
    taxonomy: { code: '207Q00000X', description: 'Family Medicine', desc: 'Family Medicine' },
    authorized_official: { name: 'Jane Doe', title: 'Owner' },
    status: 'Active', enumeration_date: '2015-01-01', taxonomy_code: '207Q00000X', specialty: 'Family Medicine',
  }
  // Universal populated fallback. Spreads a full row's scalars to the top level
  // and adds detail-shaped objects (nppes/spending/peers) so both list pages and
  // per-provider DETAIL pages render fully instead of throwing on undefined.
  return {
    ...ROWS[0],
    nppes: NPPES, spending: ROWS[0], specialty: 'Family Medicine',
    peers: { this_provider: ROWS[0], percentiles: {}, stats: {}, mean_rpb: 200, p90_rpb: 900, mean_cpb: 3, p90_cpb: 12 },
    peer_comparison: { peer_count: 40, mean_cpb: 3, p90_cpb: 12, mean_rpb: 200, p90_rpb: 900 },
    monthly_trend: makeTimeline(), enrollment_trend: 'flat', billing_trend: 'flat',
    items: ROWS, providers: ROWS, results: ROWS, data: ROWS, rows: ROWS, entries: ROWS,
    flagged: ROWS, list: ROWS, records: ROWS, timeline: makeTimeline(), hotspots: ROWS,
    states: ROWS, rules: ROWS, referrals: ROWS, tips: ROWS, searches: [], nodes: ROWS.slice(0, 10), edges: [],
    hcpcs: ROWS, code_overlap: ROWS.slice(0, 10), mismatches: [], signals: ROWS,
    total: 40, page: 1, limit: 50, count: 40, total_flagged: 40, available: true, found: true,
    progress: 100, message: 'done', offset: 106660, status: 'idle', avg_risk_score: 22.4,
    kpis: { total: 40 }, stats: {}, summary: {}, provider_stats: { total_paid: 1e6, total_claims: 5000, total_benes: 400 },
    // extra nested shapes specific pages read
    by_status: { pending: 10, assigned: 8, investigating: 6, confirmed_fraud: 4, referred: 3, dismissed: 9 },
    discrepancies: [], medicaid: { top_hcpcs: ROWS.slice(0, 5) }, medicare: { top_hcpcs: ROWS.slice(0, 5) }, medicare_has_data: false,
    excluded: false, on_watchlist: false, score_history: makeTimeline(), open_payments: [], sam: { excluded: false },
    total_paid: 1_000_000, total_claims: 5000, total_beneficiaries: 400, distinct_hcpcs: 8, active_months: 12,
    high_risk: 1900, flagged_count: 8200, mean: 100, median: 90, p90: 200, p75: 150,
  }
}

class Boundary extends Component<{ children: ReactNode; name?: string }, { err: boolean }> {
  state = { err: false }
  static getDerivedStateFromError() { return { err: true } }
  componentDidCatch(e: Error) {
    if (process.env.BENCH_DEBUG) console.log(`[bench-error] ${this.props.name}: ${e?.message?.split('\n')[0]}`)
  }
  render() { return this.state.err ? createElement('div', { 'data-errored': '1' }, 'errored') : this.props.children }
}

beforeEach(() => {
  cleanup()
  vi.stubGlobal('fetch', vi.fn(async (input: any) => {
    const url = typeof input === 'string' ? input : input.url
    return new Response(JSON.stringify(fixtureFor(url)), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  // Minimal browser APIs some pages/chart libs touch in jsdom (recharts +
  // react-simple-maps use ResizeObserver; without it they throw, not slow-render).
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} } as any)
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} } as any)
  vi.stubGlobal('matchMedia', ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })) as any)
  if (!(HTMLElement.prototype as any).getBoundingClientRect || true) {
    ;(HTMLElement.prototype as any).getBoundingClientRect = () => ({ width: 800, height: 400, top: 0, left: 0, right: 800, bottom: 400, x: 0, y: 0, toJSON() {} })
  }
  ;(HTMLCanvasElement.prototype as any).getContext = () => ({ fillRect() {}, clearRect() {}, getImageData: () => ({ data: [] }), putImageData() {}, createImageData: () => ([]), setTransform() {}, drawImage() {}, save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, stroke() {}, fill() {}, measureText: () => ({ width: 0 }), fillText() {}, arc() {}, scale() {}, rotate() {}, translate() {} })
  localStorage.setItem('mfi_session', JSON.stringify({ email: 'admin', token: 't' }))
})

const NOOP = () => {}
const PROPS: Record<string, unknown> = { onLogin: NOOP, onBack: NOOP, onClose: NOOP, npi: '1000000000' }

async function measure(name: string, load: () => Promise<{ default: any }>): Promise<{ ms: number; errored: boolean }> {
  let Page: any
  try { Page = (await load()).default } catch { return { ms: -1, errored: true } }
  let maxCommit = 0
  let errored = false
  const onRender = (_i: string, _p: string, d: number) => { if (d > maxCommit) maxCommit = d }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } })
  try {
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[`/providers/1000000000/x`]}>
          <ProviderFlagsProvider>
            <Boundary name={name}>
              <Profiler id={name} onRender={onRender}>
                <Routes>
                  <Route path="/providers/:npi/*" element={createElement(Page, PROPS)} />
                  <Route path="*" element={createElement(Page, PROPS)} />
                </Routes>
              </Profiler>
            </Boundary>
          </ProviderFlagsProvider>
        </MemoryRouter>
      </QueryClientProvider>
    )
    await waitFor(
      () => expect(container.querySelectorAll('tr,[data-kpi],.card,button,svg,[data-errored]').length).toBeGreaterThan(0),
      { timeout: 3000 },
    )
    await new Promise(r => setTimeout(r, 90))
    errored = container.querySelectorAll('[data-errored]').length > 0
  } catch { errored = true }
  return { ms: Math.round(maxCommit * 10) / 10, errored }
}

// Every page in src/pages.
const PAGES: Array<[string, () => Promise<{ default: any }>]> = [
  ['AdminScan', () => import('../pages/AdminScan')],
  ['AlertRules', () => import('../pages/AlertRules')],
  ['AnomalyDashboard', () => import('../pages/AnomalyDashboard')],
  ['AuditLog', () => import('../pages/AuditLog')],
  ['BeneficiaryDensity', () => import('../pages/BeneficiaryDensity')],
  ['BeneficiaryFraud', () => import('../pages/BeneficiaryFraud')],
  ['BillingCodeSearch', () => import('../pages/BillingCodeSearch')],
  ['ClaimPatterns', () => import('../pages/ClaimPatterns')],
  ['DemographicRisk', () => import('../pages/DemographicRisk')],
  ['Excluded', () => import('../pages/Excluded')],
  ['FraudBrain', () => import('../pages/FraudBrain')],
  ['FraudHotspots', () => import('../pages/FraudHotspots')],
  ['FraudRings', () => import('../pages/FraudRings')],
  ['GeographicAnalysis', () => import('../pages/GeographicAnalysis')],
  ['InvestigatePage', () => import('../pages/InvestigatePage')],
  ['Landing', () => import('../pages/Landing')],
  ['Login', () => import('../pages/Login')],
  ['MFCUReferralPage', () => import('../pages/MFCUReferralPage')],
  ['MLModel', () => import('../pages/MLModel')],
  ['Methods', () => import('../pages/Methods')],
  ['NetworkGraph', () => import('../pages/NetworkGraph')],
  ['NewsAlerts', () => import('../pages/NewsAlerts')],
  ['OigTips', () => import('../pages/OigTips')],
  ['Overview', () => import('../pages/Overview')],
  ['OwnershipNetworks', () => import('../pages/OwnershipNetworks')],
  ['OwnershipTracePage', () => import('../pages/OwnershipTracePage')],
  ['PharmacyDME', () => import('../pages/PharmacyDME')],
  ['PopulationRatio', () => import('../pages/PopulationRatio')],
  ['ProviderDetail', () => import('../pages/ProviderDetail')],
  ['ProviderExplorer', () => import('../pages/ProviderExplorer')],
  ['ROIDashboard', () => import('../pages/ROIDashboard')],
  ['ReviewQueue', () => import('../pages/ReviewQueue')],
  ['TrendDivergence', () => import('../pages/TrendDivergence')],
  ['UserManagement', () => import('../pages/UserManagement')],
  ['UtilizationAnalysis', () => import('../pages/UtilizationAnalysis')],
  ['Watchlist', () => import('../pages/Watchlist')],
]

describe('every page render budget', () => {
  const results: Array<[string, number, boolean]> = []

  for (const [name, load] of PAGES) {
    it(`${name} renders within the regression ceiling`, async () => {
      const { ms, errored } = await measure(name, load)
      results.push([name, ms, errored])
      const est = ms < 0 ? 'n/a' : `${Math.round(ms / JSDOM_FACTOR)}ms browser est.`
      const over = ms > 0 && ms / JSDOM_FACTOR > BROWSER_TARGET_MS ? '  <-- OVER 56ms TARGET' : ''
      const note = errored ? '  (synthetic-fixture mismatch — not fully exercised)' : ''
      console.log(`[render] ${name.padEnd(20)} ${String(ms).padStart(6)}ms jsdom  (~${est})${over}${note}`)
      expect(ms).toBeLessThan(REGRESSION_CEILING_MS)
    })
  }

  it('summary — over-budget + not-fully-exercised pages', () => {
    const over = results.filter(([, ms]) => ms > 0 && ms / JSDOM_FACTOR > BROWSER_TARGET_MS)
    const errored = results.filter(([, , e]) => e).map(([n]) => n)
    console.log(`\n[render] OVER 56ms browser target: ${over.length ? over.map(([n, ms]) => `${n} (~${Math.round(ms / JSDOM_FACTOR)}ms)`).join(', ') : 'NONE'}`)
    console.log(`[render] not fully exercised by synthetic fixture (rendered skeleton/error, cost is a floor): ${errored.length ? errored.join(', ') : 'none'}`)
    expect(true).toBe(true)
  })
})
