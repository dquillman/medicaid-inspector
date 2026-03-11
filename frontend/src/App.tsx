import { useState, useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import Overview from './pages/Overview'
import ProviderExplorer from './pages/ProviderExplorer'
import AnomalyDashboard from './pages/AnomalyDashboard'
import ProviderDetail from './pages/ProviderDetail'
import NetworkGraph from './pages/NetworkGraph'
import ReviewQueue from './pages/ReviewQueue'
import AlertRules from './pages/AlertRules'
import AuditLog from './pages/AuditLog'
import GeographicAnalysis from './pages/GeographicAnalysis'
import ROIDashboard from './pages/ROIDashboard'
import OwnershipNetworks from './pages/OwnershipNetworks'
import AdminScan from './pages/AdminScan'
import DemographicRisk from './pages/DemographicRisk'
import FraudHotspots from './pages/FraudHotspots'
import BeneficiaryDensity from './pages/BeneficiaryDensity'
import UtilizationAnalysis from './pages/UtilizationAnalysis'
import PopulationRatio from './pages/PopulationRatio'
import TrendDivergence from './pages/TrendDivergence'
import Watchlist from './pages/Watchlist'
import FraudRings from './pages/FraudRings'
import NewsAlerts from './pages/NewsAlerts'
import MLModel from './pages/MLModel'
import ClaimPatterns from './pages/ClaimPatterns'
import BeneficiaryFraud from './pages/BeneficiaryFraud'
import PharmacyDME from './pages/PharmacyDME'
import UserManagement from './pages/UserManagement'
import Landing from './pages/Landing'
import Login from './pages/Login'
import NotificationBell from './components/NotificationBell'

const NAV = [
  { to: '/',           label: 'Overview'      },
  { to: '/providers',  label: 'Providers'     },
  { to: '/anomalies',  label: 'Anomalies'     },
  { to: '/network',    label: 'Network'       },
  { to: '/review',     label: 'Review Queue'  },
  { to: '/watchlist',  label: 'Watchlist'     },
  { to: '/geographic', label: 'Geographic'    },
]

const ANALYTICS_NAV = [
  { to: '/rings',              label: 'Fraud Rings'       },
  { to: '/hotspots',           label: 'Fraud Hotspots'    },
  { to: '/claim-patterns',     label: 'Claim Patterns'    },
  { to: '/beneficiary-fraud',  label: 'Beneficiary Fraud' },
  { to: '/pharmacy-dme',       label: 'Pharmacy & DME'    },
  { to: '/news',               label: 'News & Legal'      },
  { to: '/demographics',       label: 'Demographics'      },
  { to: '/trends',             label: 'Trends'            },
  { to: '/utilization',        label: 'Utilization'       },
  { to: '/population',         label: 'Population'        },
  { to: '/density',            label: 'Density Map'       },
]

const ADMIN_NAV = [
  { to: '/admin/scan',    label: 'Scan & Data'      },
  { to: '/alerts',        label: 'Alert Rules'      },
  { to: '/audit',         label: 'Audit Log'        },
  { to: '/roi',           label: 'ROI Dashboard'    },
  { to: '/ownership',     label: 'Ownership'        },
  { to: '/ml-model',      label: 'ML Model'         },
  { to: '/users',         label: 'User Management'  },
]

interface AuthUser {
  email: string
  token: string
}

function DropdownMenu({ items, label }: { items: typeof ADMIN_NAV; label: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const location = useLocation()
  const isActive = items.some(n => location.pathname.startsWith(n.to))

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={isActive ? 'btn-primary flex items-center gap-1' : 'btn-ghost flex items-center gap-1'}
        aria-label={`${label} menu`}
        aria-expanded={open}
        aria-haspopup="true"
      >
        {label}
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-48 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 py-1 max-h-[70vh] overflow-y-auto" role="menu">
          {items.map(({ to, label: itemLabel }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setOpen(false)}
              role="menuitem"
              className={({ isActive: active }) =>
                `block px-4 py-2 text-sm transition-colors ${
                  active
                    ? 'text-blue-400 bg-gray-700'
                    : 'text-gray-300 hover:text-white hover:bg-gray-700'
                }`
              }
            >
              {itemLabel}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Settings dropdown (password change) ────────────────────────────────── */

function SettingsDropdown({ userEmail }: { userEmail: string }) {
  const [open, setOpen] = useState(false)
  const [showPwChange, setShowPwChange] = useState(false)
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setShowPwChange(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (newPw.length < 6) { setError('Password must be at least 6 characters'); return }
    if (newPw !== confirmPw) { setError('Passwords do not match'); return }
    setLoading(true)
    try {
      const token = JSON.parse(localStorage.getItem('mfi_session') || '{}').token
      const resp = await fetch('/api/auth/change-password', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      })
      const data = await resp.json()
      if (!resp.ok) { setError(data.detail || 'Failed to change password'); return }
      setSuccess('Password changed successfully')
      setOldPw(''); setNewPw(''); setConfirmPw('')
      setTimeout(() => { setShowPwChange(false); setSuccess('') }, 2000)
    } catch {
      setError('Could not reach server')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => { setOpen(!open); setShowPwChange(false) }}
        className="text-gray-400 hover:text-white transition-colors text-xs"
        aria-label="User settings"
      >
        {userEmail}
      </button>
      {open && (
        <div className="absolute top-full right-0 mt-2 w-72 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50">
          {!showPwChange ? (
            <div className="py-2">
              <div className="px-4 py-2 text-xs text-gray-500 border-b border-gray-700">
                Signed in as <span className="text-gray-300">{userEmail}</span>
              </div>
              <button
                onClick={() => setShowPwChange(true)}
                className="w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
              >
                Change Password
              </button>
            </div>
          ) : (
            <form onSubmit={handleChangePassword} className="p-4 space-y-3">
              <h3 className="text-sm font-semibold text-white">Change Password</h3>
              {error && <p className="text-xs text-red-400">{error}</p>}
              {success && <p className="text-xs text-green-400">{success}</p>}
              <input
                type="password"
                placeholder="Current password"
                value={oldPw}
                onChange={e => setOldPw(e.target.value)}
                className="w-full bg-gray-700 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                required
                aria-label="Current password"
              />
              <input
                type="password"
                placeholder="New password (min 6 chars)"
                value={newPw}
                onChange={e => setNewPw(e.target.value)}
                className="w-full bg-gray-700 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                required
                minLength={6}
                aria-label="New password"
              />
              <input
                type="password"
                placeholder="Confirm new password"
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                className="w-full bg-gray-700 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                required
                aria-label="Confirm new password"
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary text-xs py-1.5 flex-1"
                >
                  {loading ? 'Saving...' : 'Update'}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowPwChange(false); setError(''); setSuccess('') }}
                  className="btn-ghost text-xs py-1.5"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [view, setView] = useState<'landing' | 'login' | 'app'>('landing')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

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

  const handleLogin = async (username: string, password: string): Promise<string | null> => {
    try {
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await resp.json()
      if (!resp.ok) return data.detail || 'Login failed'
      const email = data.user?.username || username
      const session = { email, token: data.token }
      setUser(session)
      localStorage.setItem('mfi_session', JSON.stringify(session))
      setView('app')
      return null
    } catch {
      return 'Could not reach server'
    }
  }

  const handleRegister = async (username: string, password: string): Promise<string | null> => {
    try {
      const resp = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await resp.json()
      if (!resp.ok) return data.detail || 'Registration failed'
      const email = data.user?.username || username
      const session = { email, token: data.token }
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
          onBack={() => setView('landing')}
        />
      </BrowserRouter>
    )
  }

  // Authenticated app
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col" lang="en">
        {/* Top nav */}
        <header className="no-print bg-gray-900 border-b-2 border-red-900 px-4 md:px-6 py-3 flex items-center gap-4 md:gap-8">
          <div className="flex items-center gap-2.5">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" className="w-7 h-7 shrink-0" aria-hidden="true">
              <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
              <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" strokeWidth="1.5"/>
              <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" strokeWidth="4"/>
              <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
              <text x="28" y="33" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="11" fill="#f59e0b">$</text>
              <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" strokeWidth="4.5" strokeLinecap="round"/>
              <circle cx="46" cy="18" r="6" fill="#ef4444"/>
              <text x="46" y="22" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="9" fill="white">!</text>
            </svg>
            <span className="font-bold text-white text-base tracking-wide uppercase hidden sm:inline">
              Medicaid Fraud Inspector
            </span>
            <span className="font-bold text-white text-base tracking-wide uppercase sm:hidden">
              MFI
            </span>
          </div>

          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="lg:hidden text-gray-400 hover:text-white transition-colors ml-auto"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileMenuOpen}
          >
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              {mobileMenuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              )}
            </svg>
          </button>

          {/* Desktop nav */}
          <nav className="hidden lg:flex gap-1 items-center" role="navigation" aria-label="Main navigation">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  isActive ? 'btn-primary' : 'btn-ghost'
                }
                aria-label={label}
              >
                {label}
              </NavLink>
            ))}
            <DropdownMenu items={ANALYTICS_NAV} label="Analytics" />
            <DropdownMenu items={ADMIN_NAV} label="Admin" />
          </nav>
          <div className="ml-auto hidden lg:flex items-center gap-3 text-xs text-gray-500">
            <span className="hidden xl:inline">HHS/DOGE Medicaid Dataset</span>
            <span className="px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded font-mono text-gray-400">
              v{__APP_VERSION__}
            </span>
            <div className="flex items-center gap-2 ml-2 pl-2 border-l border-gray-800">
              <NotificationBell />
              <SettingsDropdown userEmail={user?.email ?? ''} />
              <button
                onClick={handleLogout}
                className="text-gray-500 hover:text-red-400 transition-colors"
                title="Sign out"
                aria-label="Sign out"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                </svg>
              </button>
            </div>
          </div>
        </header>

        {/* Mobile nav drawer */}
        {mobileMenuOpen && (
          <div className="lg:hidden bg-gray-900 border-b border-gray-800 px-4 py-3 space-y-2" role="navigation" aria-label="Mobile navigation">
            <div className="flex flex-wrap gap-1">
              {NAV.map(({ to, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  onClick={() => setMobileMenuOpen(false)}
                  className={({ isActive }) =>
                    isActive ? 'btn-primary text-sm' : 'btn-ghost text-sm'
                  }
                  aria-label={label}
                >
                  {label}
                </NavLink>
              ))}
            </div>
            <div className="border-t border-gray-800 pt-2">
              <p className="text-xs text-gray-500 mb-1 uppercase tracking-wider">Analytics</p>
              <div className="flex flex-wrap gap-1">
                {ANALYTICS_NAV.map(({ to, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setMobileMenuOpen(false)}
                    className={({ isActive }) =>
                      `text-xs px-2 py-1 rounded transition-colors ${
                        isActive ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
                      }`
                    }
                  >
                    {label}
                  </NavLink>
                ))}
              </div>
            </div>
            <div className="border-t border-gray-800 pt-2">
              <p className="text-xs text-gray-500 mb-1 uppercase tracking-wider">Admin</p>
              <div className="flex flex-wrap gap-1">
                {ADMIN_NAV.map(({ to, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setMobileMenuOpen(false)}
                    className={({ isActive }) =>
                      `text-xs px-2 py-1 rounded transition-colors ${
                        isActive ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
                      }`
                    }
                  >
                    {label}
                  </NavLink>
                ))}
              </div>
            </div>
            <div className="border-t border-gray-800 pt-2 flex items-center gap-3">
              <NotificationBell />
              <span className="text-xs text-gray-400">{user?.email}</span>
              <button
                onClick={handleLogout}
                className="text-xs text-red-400 hover:text-red-300 ml-auto"
                aria-label="Sign out"
              >
                Sign out
              </button>
            </div>
          </div>
        )}

        {/* Page content */}
        <main className="flex-1 p-4 md:p-6" role="main">
          <Routes>
            <Route path="/"                  element={<Overview />} />
            <Route path="/providers"         element={<ProviderExplorer />} />
            <Route path="/providers/:npi"    element={<ProviderDetail />} />
            <Route path="/anomalies"         element={<AnomalyDashboard />} />
            <Route path="/network"           element={<NetworkGraph />} />
            <Route path="/review"            element={<ReviewQueue />} />
            <Route path="/watchlist"         element={<Watchlist />} />
            <Route path="/geographic"        element={<GeographicAnalysis />} />
            <Route path="/admin/scan"        element={<AdminScan />} />
            <Route path="/alerts"            element={<AlertRules />} />
            <Route path="/audit"             element={<AuditLog />} />
            <Route path="/roi"               element={<ROIDashboard />} />
            <Route path="/ownership"         element={<OwnershipNetworks />} />
            <Route path="/demographics"     element={<DemographicRisk />} />
            <Route path="/hotspots"         element={<FraudHotspots />} />
            <Route path="/density"          element={<BeneficiaryDensity />} />
            <Route path="/utilization"      element={<UtilizationAnalysis />} />
            <Route path="/population"       element={<PopulationRatio />} />
            <Route path="/trends"           element={<TrendDivergence />} />
            <Route path="/rings"            element={<FraudRings />} />
            <Route path="/news"             element={<NewsAlerts />} />
            <Route path="/ml-model"         element={<MLModel />} />
            <Route path="/claim-patterns"  element={<ClaimPatterns />} />
            <Route path="/beneficiary-fraud" element={<BeneficiaryFraud />} />
            <Route path="/pharmacy-dme"    element={<PharmacyDME />} />
            <Route path="/users"            element={<UserManagement />} />
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
