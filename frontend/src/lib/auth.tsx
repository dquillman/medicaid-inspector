import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

/**
 * Single source of truth for identity + role.
 *
 * HISTORY: there used to be TWO parallel auth systems — App.tsx stored the real
 * session under `mfi_session` (what the API layer reads), while this provider
 * kept its own `mfi_token`/`mfi_user` keys that the real login NEVER populated.
 * So `useAuth()` / `isAdmin` were always empty, silently breaking every consumer
 * (a role-gated button rendered nothing; UserManagement's "you" markers never
 * showed). This provider now reads the SAME `mfi_session` the app actually uses
 * and hydrates the role from the backend (`mfi_session` itself carries no role).
 */

export interface AuthUser {
  username: string
  role: 'admin' | 'investigator' | 'analyst' | 'viewer'
  display_name: string
  created_at?: number
}

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  isAdmin: boolean
  isInvestigator: boolean
  isAnalyst: boolean
  canModifyReview: boolean
  canRunScans: boolean
  /** Re-read the session + role (call after login/logout in the same tab). */
  refresh: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

// The ONE token store — shared with App.tsx and lib/api.ts's authHeaders().
const SESSION_KEY = 'mfi_session'
const API_BASE = (import.meta.env.VITE_API_BASE as string) || '/api'

// App.tsx dispatches this after it writes/clears mfi_session so this provider
// re-hydrates in the SAME tab (the native `storage` event only fires in OTHER
// tabs). Exported so App.tsx imports the exact event name.
export const AUTH_CHANGED_EVENT = 'mfi-auth-changed'
export function notifyAuthChanged() {
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
}

function readToken(): string | null {
  try {
    const s = JSON.parse(localStorage.getItem(SESSION_KEY) || '{}')
    return s?.token || null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setTokenState] = useState<string | null>(null)

  const hydrate = useCallback(async () => {
    const tok = readToken()
    setTokenState(tok)
    if (!tok) {
      setUser(null)
      return
    }
    // Role lives on the backend; mfi_session has only {email, token}. Fetch it
    // with a raw request (NOT the api.ts helper, whose 401 path force-redirects
    // — a background identity check must not hijack navigation).
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: { Authorization: `Bearer ${tok}` },
      })
      if (res.ok) {
        const data = (await res.json()) as { user?: AuthUser }
        setUser(data?.user ?? null)
      } else if (res.status === 401 || res.status === 403) {
        setUser(null) // stale/invalid token — App.tsx's own flow handles logout UX
      }
      // other errors (network/5xx): leave prior user as-is (degraded, not logged out)
    } catch {
      // network failure — keep whatever we have; don't flip to logged-out
    }
  }, [])

  useEffect(() => {
    void hydrate()
    const onChange = () => void hydrate()
    window.addEventListener(AUTH_CHANGED_EVENT, onChange) // same-tab (App.tsx)
    window.addEventListener('storage', onChange) // other tabs (login/logout elsewhere)
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, onChange)
      window.removeEventListener('storage', onChange)
    }
  }, [hydrate])

  const role = user?.role || 'viewer'
  const isAdmin = role === 'admin'
  const isInvestigator = role === 'investigator' || isAdmin
  const isAnalyst = role === 'analyst' || isInvestigator

  const value: AuthContextType = {
    user,
    token,
    isAuthenticated: !!user,
    isAdmin,
    isInvestigator,
    isAnalyst,
    canModifyReview: isInvestigator,
    canRunScans: isAnalyst,
    refresh: () => void hydrate(),
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
