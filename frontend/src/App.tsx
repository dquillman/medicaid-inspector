import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Overview from './pages/Overview'
import ProviderExplorer from './pages/ProviderExplorer'
import AnomalyDashboard from './pages/AnomalyDashboard'
import ProviderDetail from './pages/ProviderDetail'
import NetworkGraph from './pages/NetworkGraph'
import ReviewQueue from './pages/ReviewQueue'

const NAV = [
  { to: '/',           label: 'Overview'      },
  { to: '/providers',  label: 'Providers'     },
  { to: '/anomalies',  label: 'Anomalies'     },
  { to: '/network',    label: 'Network'       },
  { to: '/review',     label: 'Review Queue'  },
]

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        {/* Top nav */}
        <header className="no-print bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-8">
          <div className="flex items-center gap-2">
            <span className="text-red-500 text-xl font-bold">⚠</span>
            <span className="font-semibold text-white text-sm tracking-wide">
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
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
