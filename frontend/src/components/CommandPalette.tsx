import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

interface NavItem {
  to: string
  label: string
  category: string
}

const ALL_NAV: NavItem[] = [
  { to: '/',           label: 'Overview',          category: 'Main' },
  { to: '/providers',  label: 'Providers',         category: 'Main' },
  { to: '/anomalies',  label: 'Anomalies',         category: 'Main' },
  { to: '/network',    label: 'Network',           category: 'Main' },
  { to: '/review',     label: 'Review Queue',      category: 'Main' },
  { to: '/watchlist',  label: 'Watchlist',         category: 'Main' },
  { to: '/geographic', label: 'Geographic',        category: 'Main' },
  { to: '/rings',              label: 'Fraud Rings',       category: 'Analytics' },
  { to: '/hotspots',           label: 'Fraud Hotspots',    category: 'Analytics' },
  { to: '/billing-codes',     label: 'Billing Codes',     category: 'Analytics' },
  { to: '/claim-patterns',    label: 'Claim Patterns',    category: 'Analytics' },
  { to: '/beneficiary-fraud', label: 'Beneficiary Fraud', category: 'Analytics' },
  { to: '/pharmacy-dme',      label: 'Pharmacy & DME',    category: 'Analytics' },
  { to: '/news',               label: 'News & Legal',      category: 'Analytics' },
  { to: '/demographics',      label: 'Demographics',      category: 'Analytics' },
  { to: '/trends',             label: 'Trends',            category: 'Analytics' },
  { to: '/utilization',        label: 'Utilization',       category: 'Analytics' },
  { to: '/population',         label: 'Population',        category: 'Analytics' },
  { to: '/density',            label: 'Density Map',       category: 'Analytics' },
  { to: '/admin/scan',    label: 'Scan & Data',      category: 'Admin' },
  { to: '/alerts',        label: 'Alert Rules',      category: 'Admin' },
  { to: '/audit',         label: 'Audit Log',        category: 'Admin' },
  { to: '/roi',           label: 'ROI Dashboard',    category: 'Admin' },
  { to: '/ownership',     label: 'Ownership',        category: 'Admin' },
  { to: '/ml-model',      label: 'ML Model',         category: 'Admin' },
  { to: '/users',         label: 'User Management',  category: 'Admin' },
]

const ALL_NAV_AS_ROUTES: RouteResult[] = ALL_NAV.map(n => ({
  kind: 'route',
  to: n.to,
  label: n.label,
  category: n.category,
}))

function fuzzyMatch(text: string, query: string): boolean {
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  let qi = 0
  for (let i = 0; i < lower.length && qi < q.length; i++) {
    if (lower[i] === q[qi]) qi++
  }
  return qi === q.length
}

interface RouteResult {
  kind: 'route'
  to: string
  label: string
  category: string
}

interface ProviderResult {
  kind: 'provider'
  npi: string
  name: string
  state: string
  city: string
}

type PaletteResult = RouteResult | ProviderResult

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [providerResults, setProviderResults] = useState<ProviderResult[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  useEffect(() => {
    if (open) {
      setQuery('')
      setSelectedIdx(0)
      setProviderResults([])
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)

    if (query.length < 3) {
      setProviderResults([])
      return
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const data = await api.searchProviders(query)
        setProviderResults(
          data.slice(0, 5).map(r => ({
            kind: 'provider' as const,
            npi: r.npi,
            name: r.name,
            state: r.state,
            city: r.city,
          }))
        )
      } catch {
        setProviderResults([])
      }
    }, 300)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  const results: PaletteResult[] = useMemo(() => {
    const routes = query
      ? ALL_NAV_AS_ROUTES.filter(n => fuzzyMatch(n.label, query))
      : ALL_NAV_AS_ROUTES
    return [...routes, ...providerResults]
  }, [query, providerResults])

  // Clamp selection when results shrink
  useEffect(() => {
    setSelectedIdx(prev => {
      const max = Math.max(results.length - 1, 0)
      return prev > max ? max : prev
    })
  }, [results])

  const close = useCallback(() => setOpen(false), [])

  const navigateTo = useCallback((result: PaletteResult) => {
    navigate(result.kind === 'route' ? result.to : `/providers/${result.npi}`)
    close()
  }, [navigate, close])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIdx(prev => Math.min(prev + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIdx(prev => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter' && results.length > 0) {
      e.preventDefault()
      navigateTo(results[selectedIdx])
    } else if (e.key === 'Escape') {
      close()
    }
  }, [results, selectedIdx, navigateTo, close])

  useEffect(() => {
    if (!listRef.current) return
    const el = listRef.current.children[selectedIdx] as HTMLElement | undefined
    el?.scrollIntoView({ block: 'nearest' })
  }, [selectedIdx])

  if (!open) return null

  const rowClass = (selected: boolean) =>
    `w-full text-left px-4 py-2.5 flex items-center gap-3 transition-colors cursor-pointer ${
      selected ? 'bg-gray-800' : 'hover:bg-gray-800/50'
    }`

  return (
    <div
      className="fixed inset-0 z-[60] bg-black/60"
      onClick={close}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg mx-auto mt-[20vh] shadow-2xl"
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-center border-b border-gray-700 px-4">
          <svg className="w-4 h-4 text-gray-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => { setQuery(e.target.value); setSelectedIdx(0) }}
            placeholder="Search pages and providers..."
            className="input w-full border-0 bg-transparent focus:ring-0 text-sm py-3 pl-3"
            aria-label="Search"
          />
          <kbd className="hidden sm:inline-block text-[10px] text-gray-500 border border-gray-700 rounded px-1.5 py-0.5 font-mono">
            ESC
          </kbd>
        </div>

        <div ref={listRef} className="max-h-72 overflow-y-auto divide-y divide-gray-800" role="listbox">
          {results.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-gray-500">
              No results found
            </div>
          )}
          {results.map((result, i) => {
            const isSelected = i === selectedIdx
            if (result.kind === 'route') {
              return (
                <button
                  key={`route-${result.to}`}
                  role="option"
                  aria-selected={isSelected}
                  className={rowClass(isSelected)}
                  onClick={() => navigateTo(result)}
                  onMouseEnter={() => setSelectedIdx(i)}
                >
                  <span className="text-[10px] uppercase tracking-wider text-gray-500 w-16 shrink-0">
                    {result.category}
                  </span>
                  <span className="text-sm text-gray-100">{result.label}</span>
                  <span className="ml-auto text-xs text-gray-600 font-mono">{result.to}</span>
                </button>
              )
            }
            return (
              <button
                key={`provider-${result.npi}`}
                role="option"
                aria-selected={isSelected}
                className={rowClass(isSelected)}
                onClick={() => navigateTo(result)}
                onMouseEnter={() => setSelectedIdx(i)}
              >
                <span className="text-[10px] uppercase tracking-wider text-blue-400 w-16 shrink-0">
                  Provider
                </span>
                <span className="text-sm text-gray-100 truncate">
                  {result.name || result.npi}
                </span>
                <span className="ml-auto text-xs text-gray-500 font-mono">{result.npi}</span>
                {result.state && (
                  <span className="text-xs text-gray-500">{result.city ? `${result.city}, ` : ''}{result.state}</span>
                )}
              </button>
            )
          })}
        </div>

        <div className="border-t border-gray-700 px-4 py-2 flex items-center gap-4 text-[10px] text-gray-500">
          <span>
            <kbd className="border border-gray-700 rounded px-1 py-0.5 font-mono mr-1">Up</kbd>
            <kbd className="border border-gray-700 rounded px-1 py-0.5 font-mono mr-1">Down</kbd>
            to navigate
          </span>
          <span>
            <kbd className="border border-gray-700 rounded px-1 py-0.5 font-mono mr-1">Enter</kbd>
            to select
          </span>
          <span>
            <kbd className="border border-gray-700 rounded px-1 py-0.5 font-mono mr-1">Esc</kbd>
            to close
          </span>
        </div>
      </div>
    </div>
  )
}
