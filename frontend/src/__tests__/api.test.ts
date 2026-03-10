/**
 * Tests for the API helper functions with mocked fetch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// We need to mock fetch before importing api
const mockFetch = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch)
  // Mock window.location.origin for URL construction
  vi.stubGlobal('location', { origin: 'http://localhost:5200' })
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
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(summaryData),
    })

    const { api } = await import('../lib/api')
    const result = await api.summary()
    expect(result).toEqual(summaryData)
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/summary')
    )
  })

  it('providers() includes query params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ providers: [], total: 0, page: 1, limit: 50 }),
    })

    const { api } = await import('../lib/api')
    await api.providers({ search: 'test', states: 'TX', page: 1, limit: 10 })
    const calledUrl = mockFetch.mock.calls[mockFetch.mock.calls.length - 1][0]
    expect(calledUrl).toContain('search=test')
    expect(calledUrl).toContain('states=TX')
  })

  it('throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Internal Server Error'),
    })

    const { api } = await import('../lib/api')
    await expect(api.summary()).rejects.toThrow('API error 500')
  })

  it('prescanStatus() calls /api/prescan/status', async () => {
    const statusData = { status: 0, message: 'Idle', auto_mode: false }
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(statusData),
    })

    const { api } = await import('../lib/api')
    const result = await api.prescanStatus()
    expect(result).toEqual(statusData)
  })

  it('scanBatch() sends POST with batch_size', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ started: true }),
    })

    const { api } = await import('../lib/api')
    await api.scanBatch(200)
    const lastCall = mockFetch.mock.calls[mockFetch.mock.calls.length - 1]
    expect(lastCall[0]).toContain('/api/prescan/scan-batch')
    const body = JSON.parse(lastCall[1].body)
    expect(body.batch_size).toBe(200)
  })
})
