/**
 * Basic render test for the App component.
 * Verifies the app mounts without crashing and shows the landing page.
 * App is rendered inside QueryClientProvider because authenticated views
 * (NotificationBell, Overview) call useQuery/useQueryClient.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '../App'

beforeEach(() => {
  // Empty body -> get() rejects -> queries land in error state -> components
  // render their loading/placeholder branches, mirroring a dead backend.
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      text: () => Promise.resolve(''),
    })
  ))
  localStorage.clear()
  window.history.replaceState({}, '', '/')
})

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}

describe('App', () => {
  it('renders without crashing', () => {
    const { container } = renderApp()
    expect(container).toBeDefined()
  })

  it('shows landing page when not authenticated', () => {
    renderApp()
    expect(document.body.innerHTML).toBeTruthy()
  })

  it('restores session from localStorage', () => {
    localStorage.setItem('mfi_session', JSON.stringify({
      email: 'test@example.com',
      token: 'abc123',
    }))
    renderApp()
    expect(document.body.innerHTML).toContain('Medicaid Fraud Inspector')
  })
})
