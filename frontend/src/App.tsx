import { useState, useEffect, useRef, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { useClickOutside } from './hooks/useClickOutside'
import Sidebar, { useSidebarCollapsed } from './components/Sidebar'
import PageTransition from './components/PageTransition'
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
import Breadcrumbs from './components/Breadcrumbs'
import BillingCodeSearch from './pages/BillingCodeSearch'
import Login from './pages/Login'
import NotificationBell from './components/NotificationBell'
import CommandPalette from './components/CommandPalette'
import KeyboardShortcuts from './components/KeyboardShortcuts'
import { mutate } from './lib/api'
import { useTheme } from './lib/theme'

const SESSION_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000 // 30 days

interface AuthUser {
  email: string
  token: string
  savedAt?: number
}

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

  useClickOutside(ref, useCallback(() => {
    setOpen(false)
    setShowPwChange(false)
  }, []))

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (newPw.length < 6) { setError('Password must be at least 6 characters'); return }
    if (newPw !== confirmPw) { setError('Passwords do not match'); return }
    setLoading(true)
    try {
      await mutate<{ ok: boolean }>('PATCH', '/auth/change-password', { old_password: oldPw, new_password: newPw })
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

function AnimatedRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait">
      <PageTransition key={location.pathname}>
        <Routes location={location}>
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
          <Route path="/billing-codes"   element={<BillingCodeSearch />} />
          <Route path="/claim-patterns"  element={<ClaimPatterns />} />
          <Route path="/beneficiary-fraud" element={<BeneficiaryFraud />} />
          <Route path="/pharmacy-dme"    element={<PharmacyDME />} />
          <Route path="/users"            element={<UserManagement />} />
          <Route path="*"                  element={<Navigate to="/" replace />} />
        </Routes>
      </PageTransition>
    </AnimatePresence>
  )
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [view, setView] = useState<'landing' | 'login' | 'app'>('landing')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const { collapsed, toggle: toggleCollapsed } = useSidebarCollapsed()
  const sidebarMargin = collapsed ? 'lg:ml-16' : 'lg:ml-56'
  const { theme, toggleTheme } = useTheme()

  // Restore session from localStorage (with expiry check)
  useEffect(() => {
    const saved = localStorage.getItem('mfi_session')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        if (parsed.token && parsed.email) {
          const age = Date.now() - (parsed.savedAt ?? 0)
          if (parsed.savedAt && age > SESSION_MAX_AGE_MS) {
            // Token expired -- clear it
            localStorage.removeItem('mfi_session')
          } else {
            setUser(parsed)
            setView('app')
          }
        }
      } catch { /* ignore */ }
    }
  }, [])

  const authRequest = async (
    path: string,
    username: string,
    password: string,
    failLabel: string,
  ): Promise<string | null> => {
    try {
      const data = await mutate<{ token: string; user: { username: string } }>('POST', path, { username, password })
      const email = data.user?.username || username
      const session: AuthUser = { email, token: data.token, savedAt: Date.now() }
      setUser(session)
      localStorage.setItem('mfi_session', JSON.stringify(session))
      setView('app')
      return null
    } catch (e) {
      return e instanceof Error ? e.message : failLabel
    }
  }

  const handleLogin = (username: string, password: string) =>
    authRequest('/auth/login', username, password, 'Login failed')

  const handleRegister = async (username: string, password: string, displayName?: string) => {
    try {
      const data = await mutate<{ token: string; user: { username: string } }>('POST', '/auth/register', {
        username,
        password,
        display_name: displayName || username,
      })
      const email = data.user?.username || username
      const session: AuthUser = { email, token: data.token, savedAt: Date.now() }
      setUser(session)
      localStorage.setItem('mfi_session', JSON.stringify(session))
      setView('app')
      return null
    } catch (e) {
      return e instanceof Error ? e.message : 'Registration failed'
    }
  }

  const handleLogout = () => {
    setUser(null)
    localStorage.removeItem('mfi_session')
    setView('landing')
  }

  // Single BrowserRouter with conditional views based on auth state
  return (
    <BrowserRouter>
      {view === 'landing' ? (
        <Landing onLogin={() => setView('login')} />
      ) : view === 'login' ? (
        <Login
          onLogin={handleLogin}
          onRegister={handleRegister}
          onBack={() => setView('landing')}
        />
      ) : (
      <div className="min-h-screen flex flex-col" lang="en">
        {/* Slim top bar */}
        <header className="no-print h-12 bg-gray-900 border-b border-gray-800 flex items-center px-4 z-50 fixed top-0 left-0 right-0">
          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="lg:hidden text-gray-400 hover:text-white transition-colors mr-3"
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

          {/* Logo + title */}
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

          {/* Right side controls */}
          <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
            <span className="hidden xl:inline">HHS/DOGE Medicaid Dataset</span>
            <span className="px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded font-mono text-gray-400">
              v{__APP_VERSION__}
            </span>
            <button
              onClick={toggleTheme}
              className="text-gray-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-gray-800"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
            </button>
            <div className="flex items-center gap-2 ml-2 pl-2 border-l border-gray-800">
              <NotificationBell />
              <span className="hidden md:block">
                <SettingsDropdown userEmail={user?.email ?? ''} />
              </span>
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

        {/* Sidebar */}
        <Sidebar
          mobileOpen={mobileMenuOpen}
          onMobileClose={() => setMobileMenuOpen(false)}
          collapsed={collapsed}
          onToggleCollapse={toggleCollapsed}
        />

        {/* Breadcrumb navigation */}
        <Breadcrumbs />

        {/* Page content */}
        <main
          className={`flex-1 p-4 md:p-6 mt-12 transition-[margin-left] duration-200 ${sidebarMargin}`}
          role="main"
        >
          <AnimatedRoutes />
        </main>

        {/* Footer */}
        <footer
          className={`no-print py-4 text-center transition-[margin-left] duration-200 ${sidebarMargin}`}
        >
          <div className="divider mb-4 mx-auto max-w-2xl" />
          <p className="text-[10px] text-gray-600 uppercase tracking-[0.2em] font-medium">
            Powered by Medicaid Inspector &middot; Data sourced from CMS/HHS &middot; For authorized use only
          </p>
        </footer>

        <CommandPalette />
        <KeyboardShortcuts />
      </div>
      )}
    </BrowserRouter>
  )
}
