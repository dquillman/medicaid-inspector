import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { get, mutate } from './api'

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
  login: (username: string, password: string) => Promise<string | null>
  logout: () => void
  isAdmin: boolean
  isInvestigator: boolean
  isAnalyst: boolean
  canModifyReview: boolean
  canRunScans: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

const TOKEN_KEY = 'mfi_token'
const USER_KEY = 'mfi_user'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(null)

  // Restore session from localStorage
  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_KEY)
    const savedUser = localStorage.getItem(USER_KEY)
    if (savedToken && savedUser) {
      try {
        const parsed = JSON.parse(savedUser)
        setToken(savedToken)
        setUser(parsed)
        // Verify the token is still valid
        get<{ user: AuthUser }>('/auth/me')
          .then(data => {
            if (data?.user) {
              setUser(data.user)
              localStorage.setItem(USER_KEY, JSON.stringify(data.user))
            }
          })
          .catch(() => {
            // Token expired/invalid or server unreachable
            // If API returned 4xx, clear session; network errors keep cached session
          })
      } catch {
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(USER_KEY)
      }
    }
  }, [])

  const login = useCallback(async (username: string, password: string): Promise<string | null> => {
    try {
      const data = await mutate<{ token: string; user: AuthUser }>('POST', '/auth/login', { username, password })
      setToken(data.token)
      setUser(data.user)
      localStorage.setItem(TOKEN_KEY, data.token)
      localStorage.setItem(USER_KEY, JSON.stringify(data.user))
      return null
    } catch (e) {
      return e instanceof Error ? e.message : 'Could not reach server'
    }
  }, [])

  const logout = useCallback(() => {
    if (token) {
      mutate<{ ok: boolean }>('POST', '/auth/logout').catch(() => {})
    }
    setToken(null)
    setUser(null)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }, [token])

  const role = user?.role || 'viewer'
  const isAdmin = role === 'admin'
  const isInvestigator = role === 'investigator' || isAdmin
  const isAnalyst = role === 'analyst' || isInvestigator
  const canModifyReview = isInvestigator
  const canRunScans = isAnalyst

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!user,
        login,
        logout,
        isAdmin,
        isInvestigator,
        isAnalyst,
        canModifyReview,
        canRunScans,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
