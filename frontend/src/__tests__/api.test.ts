/**
 * Tests for the API helper functions with mocked fetch.
 * Mocks mirror the real contract: api.ts reads bodies via res.text()
 * (see parseJsonSafe), so every mock response must implement text().
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockFetch = vi.fn()

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(data)),
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('API helper', () => {
  it('summary() calls /api/summary', async () => {
    const summaryData = {
      total_providers: 100,
      total_paid: 5000000,
      flagged_providers: 10,
    }
    mockFetch.mockResolvedValueOnce(jsonResponse(summaryData))

    const { api } = await import('../lib/api')
    const result = await api.summary()
    expect(result).toEqual(summaryData)
    const calledUrl = mockFetch.mock.calls[mockFetch.mock.calls.length - 1][0]
    expect(calledUrl).toContain('/api/summary')
  })

  it('providers() includes query params', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ providers: [], total: 0, page: 1, limit: 50 })
    )

    const { api } = await import('../lib/api')
    await api.providers({ search: 'test', states: 'TX', page: 1, limit: 10 })
    const calledUrl = mockFetch.mock.calls[mockFetch.mock.calls.length - 1][0]
    expect(calledUrl).toContain('search=test')
    expect(calledUrl).toContain('states=TX')
  })

  it('throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse('Internal Server Error', 500))

    const { api } = await import('../lib/api')
    await expect(api.summary()).rejects.toThrow('Request failed (500)')
  })

  it('surfaces the server detail message on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Scan already running' }, 409))

    const { api } = await import('../lib/api')
    await expect(api.summary()).rejects.toThrow('Scan already running')
  })

  it('prescanStatus() calls /api/prescan/status', async () => {
    const statusData = { status: 0, message: 'Idle', auto_mode: false }
    mockFetch.mockResolvedValueOnce(jsonResponse(statusData))

    const { api } = await import('../lib/api')
    const result = await api.prescanStatus()
    expect(result).toEqual(statusData)
  })

  it('scanBatch() sends POST with batch_size', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ started: true }))

    const { api } = await import('../lib/api')
    await api.scanBatch(200)
    const lastCall = mockFetch.mock.calls[mockFetch.mock.calls.length - 1]
    expect(lastCall[0]).toContain('/api/prescan/scan-batch')
    const body = JSON.parse(lastCall[1].body)
    expect(body.batch_size).toBe(200)
  })
})
