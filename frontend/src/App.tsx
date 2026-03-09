import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import Overview from './pages/Overview'
import ProviderExplorer from './pages/ProviderExplorer'
import AnomalyDashboard from './pages/AnomalyDashboard'
import ProviderDetail from './pages/ProviderDetail'
import NetworkGraph from './pages/NetworkGraph'
import ReviewQueue from './pages/ReviewQueue'
import Landing from './pages/Landing'
import Login from './pages/Login'

const NAV = [
  { to: '/',           label: 'Overview'      },
  { to: '/providers',  label: 'Providers'     },
  { to: '/anomalies',  label: 'Anomalies'     },
  { to: '/network',    label: 'Network'       },
  { to: '/review',     label: 'Review Queue'  },
]

interface AuthUser {
  email: string
  token: string
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [view, setView] = useState<'landing' | 'login' | 'app'>('landing')

  // Restore session from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('mfi_session')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        if (parsed.token && parsed.email) {
          setUser(parsed)
          setView('app')
        }
      } catch { /* ignore */ }
    }
  }, [])

  const handleLogin = async (email: string, password: string): Promise<string | null> => {
    try {
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await resp.json()
      if (!resp.ok) return data.detail || 'Login failed'
      const session = { email: data.email, token: data.token }
      setUser(session)
      localStorage.setItem('mfi_session', JSON.stringify(session))
      setView('app')
      return null
    } catch {
      return 'Could not reach server'
    }
  }

  const handleRegister = async (email: string, password: string): Promise<string | null> => {
    try {
      const resp = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await resp.json()
      if (!resp.ok) return data.detail || 'Registration failed'
      const session = { email: data.email, token: data.token }
      setUser(session)
      localStorage.setItem('mfi_session', JSON.stringify(session))
      setView('app')
      return null
    } catch {
      return 'Could not reach server'
    }
  }

  const handleLogout = () => {
    setUser(null)
    localStorage.removeItem('mfi_session')
    setView('landing')
  }

  // Landing page (not logged in)
  if (view === 'landing') {
    return (
      <BrowserRouter>
        <Landing onLogin={() => setView('login')} />
      </BrowserRouter>
    )
  }

  // Login / register page
  if (view === 'login') {
    return (
      <BrowserRouter>
        <Login
          onLogin={handleLogin}
          onRegister={handleRegister}
          onBack={() => setView('landing')}
        />
      </BrowserRouter>
    )
  }

  // Authenticated app
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        {/* Top nav */}
        <header className="no-print bg-gray-900 border-b-2 border-red-900 px-6 py-3 flex items-center gap-8">
          <div className="flex items-center gap-2.5">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" className="w-7 h-7 shrink-0">
              <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
              <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" strokeWidth="1.5"/>
              <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" strokeWidth="4"/>
              <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
              <text x="28" y="33" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="11" fill="#f59e0b">$</text>
              <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" strokeWidth="4.5" strokeLinecap="round"/>
              <circle cx="46" cy="18" r="6" fill="#ef4444"/>
              <text x="46" y="22" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="9" fill="white">!</text>
            </svg>
            <span className="font-bold text-white text-base tracking-wide uppercase">
              Medicaid Fraud Inspector
            </span>
          </div>
          <nav className="flex gap-1">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  isActive ? 'btn-primary' : 'btn-ghost'
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
            <span>HHS/DOGE Medicaid Dataset · 2018–2024</span>
            <span className="px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded font-mono text-gray-400">
              v{__APP_VERSION__}
            </span>
            <div className="flex items-center gap-2 ml-2 pl-2 border-l border-gray-800">
              <span className="text-gray-400">{user?.email}</span>
              <button
                onClick={handleLogout}
                className="text-gray-500 hover:text-red-400 transition-colors"
                title="Sign out"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                </svg>
              </button>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 p-6">
          <Routes>
            <Route path="/"                  element={<Overview />} />
            <Route path="/providers"         element={<ProviderExplorer />} />
            <Route path="/providers/:npi"    element={<ProviderDetail />} />
            <Route path="/anomalies"         element={<AnomalyDashboard />} />
            <Route path="/network"           element={<NetworkGraph />} />
            <Route path="/review"            element={<ReviewQueue />} />
            <Route path="*"                  element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        {/* Footer */}
        <footer className="no-print py-4 text-center">
          <div className="divider mb-4 mx-auto max-w-2xl" />
          <p className="text-[10px] text-gray-600 uppercase tracking-[0.2em] font-medium">
            Powered by Medicaid Inspector &middot; Data sourced from CMS/HHS &middot; For authorized use only
          </p>
        </footer>
      </div>
    </BrowserRouter>
  )
}
