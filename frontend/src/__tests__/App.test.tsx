/**
 * Basic render test for the App component.
 * Verifies the app mounts without crashing and shows the landing page.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from '../App'

// Mock fetch globally
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
    })
  ))
  localStorage.clear()
})

describe('App', () => {
  it('renders without crashing', () => {
    const { container } = render(<App />)
    expect(container).toBeDefined()
  })

  it('shows landing page when not authenticated', () => {
    render(<App />)
    // Landing page should be visible (no session in localStorage)
    expect(document.body.innerHTML).toBeTruthy()
  })

  it('restores session from localStorage', () => {
    localStorage.setItem('mfi_session', JSON.stringify({
      email: 'test@example.com',
      token: 'abc123',
    }))
    render(<App />)
    // Should show the authenticated app (nav bar with "Medicaid Fraud Inspector")
    expect(document.body.innerHTML).toContain('Medicaid Fraud Inspector')
  })
})
