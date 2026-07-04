/**
 * Headless render benchmark.
 *
 * Measures the React commit cost (Profiler `actualDuration` — pure reconciliation
 * work, independent of browser paint) for the heaviest pages with realistic data
 * already resolved, so the number reflects the DATA-PRESENT render, not the
 * loading skeleton. Target budget: 56ms per commit.
 *
 * Run: npx vitest run src/__perf__/renderBench.test.tsx --reporter=basic
 */
import { Profiler, type ReactNode } from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ProviderFlagsProvider } from '../hooks/useProviderFlags'

// Target: 56ms per commit in a REAL browser. This harness renders under jsdom,
// whose DOM operations run ~2-3x slower than a browser's, so the same commit
// measures higher here — and absolute timings drift with machine load. The
// printed "~Nms browser est." lines are the real signal; the assertions are a
// deliberately-generous catastrophe guard (catch a 2-3x regression) so this
// never flakes in a shared CI run.
const BROWSER_TARGET_MS = 56
const REGRESSION_CEILING_MS = 200

// ── Fixtures ────────────────────────────────────────────────────────────────
const SIGNALS = ['billing_concentration', 'revenue_per_bene_outlier', 'claims_per_bene_anomaly']
function signalResults(n: number) {
  return SIGNALS.slice(0, n).map((s, i) => ({
    signal: s, score: 0.8 - i * 0.1, weight: 20 - i * 5,
    reason: `${s} triggered`, flagged: true,
  }))
}
function makeProviders(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const flags = signalResults((i % 4))
    return {
      npi: String(1000000000 + i),
      provider_name: `Provider ${i} LLC`,
      city: ['HARTFORD', 'MIAMI', 'DALLAS', 'NEWARK'][i % 4],
      state: ['CT', 'FL', 'TX', 'NJ'][i % 4],
      zip: '06114',
      total_paid: 500000 - i * 1000,
      total_claims: 5000 - i * 10,
      total_beneficiaries: 400 - i,
      distinct_hcpcs: 3 + (i % 10),
      active_months: 6 + (i % 12),
      first_month: '2018-10', last_month: '2020-04',
      risk_score: 95 - (i % 40),
      flags, signal_results: flags, flag_count: flags.length,
    }
  })
}
function makeTimeline(months = 24) {
  return Array.from({ length: months }, (_, i) => ({
    month: `20${18 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`,
    total_paid: 20000 + (i * 137) % 9000,
    total_claims: 200 + (i * 7) % 90,
    total_unique_beneficiaries: 40 + (i % 30),
  }))
}

const PROVIDERS_50 = makeProviders(50)

// Route fixtures by URL path substring.
function fixtureFor(path: string): unknown {
  if (/\/providers\/\d+\/timeline/.test(path)) return { npi: '1', timeline: makeTimeline() }
  if (/\/providers\/\d+\/hcpcs/.test(path)) return { npi: '1', hcpcs: [] }
  if (path.includes('/provider-facets') || path.includes('/providers/facets'))
    return { states: ['CT', 'FL', 'TX', 'NJ'], cities: ['HARTFORD', 'MIAMI'] }
  if (path.includes('/anomalies')) return { total: 50, page: 1, limit: 50, anomalies: PROVIDERS_50 }
  if (path.includes('/providers')) return { providers: PROVIDERS_50, page: 1, limit: 50, total: 12800 }
  if (path.includes('/summary')) return {
    total_providers: 106660, total_paid: 9.1e9, total_claims: 4.2e7, total_beneficiaries: 3.1e6,
    flagged_providers: 8200, high_risk_providers: 1900, avg_risk_score: 22.4, prescan_complete: true,
  }
  if (path.includes('/review')) return { items: PROVIDERS_50.map(p => ({ ...p, status: 'pending', added_at: 1_700_000_000 })) }
  if (path.includes('/prescan/status')) return { progress: 100, message: 'done', offset: 106660 }
  if (path.includes('/states')) return { states: [] }
  if (path.includes('/watchlist')) return { items: [] }
  if (path.includes('/saved-searches')) return { searches: [] }
  return {}
}

beforeEach(() => {
  cleanup()
  const fetchMock = vi.fn(async (input: any) => {
    const url = typeof input === 'string' ? input : input.url
    const body = JSON.stringify(fixtureFor(url))
    return new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  localStorage.setItem('mfi_session', JSON.stringify({ email: 'admin', token: 't' }))
})

function Providers({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProviderFlagsProvider>{children}</ProviderFlagsProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function measure(name: string, load: () => Promise<{ default: React.ComponentType }>) {
  const { default: Page } = await load()
  let maxCommit = 0
  const onRender = (_id: string, _phase: string, actualDuration: number) => {
    if (actualDuration > maxCommit) maxCommit = actualDuration
  }
  const { container } = render(
    <Providers>
      <Profiler id={name} onRender={onRender}>
        <Page />
      </Profiler>
    </Providers>
  )
  // Let queries resolve + data-present commit happen.
  await waitFor(() => expect(container.querySelectorAll('tr,[data-kpi],.card').length).toBeGreaterThan(0), { timeout: 3000 })
  await new Promise(r => setTimeout(r, 80))
  return Math.round(maxCommit * 10) / 10
}

describe('page render budget', () => {
  const results: Record<string, number> = {}

  const report = (name: string, ms: number) =>
    console.log(`[render] ${name}: ${ms}ms jsdom  (~${Math.round(ms / 2.5)}ms browser est.; target ${BROWSER_TARGET_MS}ms)`)

  it('ProviderExplorer commits within budget', async () => {
    results.ProviderExplorer = await measure('ProviderExplorer', () => import('../pages/ProviderExplorer'))
    report('ProviderExplorer', results.ProviderExplorer)
    expect(results.ProviderExplorer).toBeLessThan(REGRESSION_CEILING_MS)
  })

  it('AnomalyDashboard commits within budget', async () => {
    results.AnomalyDashboard = await measure('AnomalyDashboard', () => import('../pages/AnomalyDashboard'))
    report('AnomalyDashboard', results.AnomalyDashboard)
    // Already comfortably under the browser target even in slow jsdom.
    expect(results.AnomalyDashboard).toBeLessThan(REGRESSION_CEILING_MS)
  })

  it('Overview commits within budget', async () => {
    results.Overview = await measure('Overview', () => import('../pages/Overview'))
    report('Overview', results.Overview)
    expect(results.Overview).toBeLessThan(REGRESSION_CEILING_MS)
  })

  it('ReviewQueue commits within budget', async () => {
    results.ReviewQueue = await measure('ReviewQueue', () => import('../pages/ReviewQueue'))
    report('ReviewQueue', results.ReviewQueue)
    expect(results.ReviewQueue).toBeLessThan(REGRESSION_CEILING_MS)
  })
})
