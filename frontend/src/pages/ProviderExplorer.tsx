import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, mutate, get } from '../lib/api'
import { fmt } from '../lib/format'
import RiskScoreBadge from '../components/RiskScoreBadge'
import { useClickOutside } from '../hooks/useClickOutside'
import { SkeletonTable } from '../components/Skeleton'

type SortDir = 'asc' | 'desc'

// ── Column filter state types ────────────────────────────────────────────────

interface RangeFilter { min: string; max: string }

interface ColFilters {
  states:    string[]   // multi-select
  cities:    string[]   // multi-select
  flag_counts: string[] // multi-select ("0","1","2","3+")
  risk:      RangeFilter
  total_paid: RangeFilter
  total_claims: RangeFilter
  active_months: RangeFilter
}

const EMPTY_FILTERS: ColFilters = {
  states: [], cities: [], flag_counts: [],
  risk: { min: '', max: '' },
  total_paid: { min: '', max: '' },
  total_claims: { min: '', max: '' },
  active_months: { min: '', max: '' },
}

function hasFilter(f: ColFilters): boolean {
  return (
    f.states.length > 0 || f.cities.length > 0 || f.flag_counts.length > 0 ||
    !!f.risk.min || !!f.risk.max ||
    !!f.total_paid.min || !!f.total_paid.max ||
    !!f.total_claims.min || !!f.total_claims.max ||
    !!f.active_months.min || !!f.active_months.max
  )
}

function colHasFilter(col: string, f: ColFilters): boolean {
  switch (col) {
    case 'state':         return f.states.length > 0
    case 'city':          return f.cities.length > 0
    case 'flag_count':    return f.flag_counts.length > 0
    case 'risk_score':    return !!f.risk.min || !!f.risk.max
    case 'total_paid':    return !!f.total_paid.min || !!f.total_paid.max
    case 'total_claims':  return !!f.total_claims.min || !!f.total_claims.max
    case 'active_months': return !!f.active_months.min || !!f.active_months.max
    default:              return false
  }
}

// ── Filter dropdown component ─────────────────────────────────────────────────

function CheckboxList({
  options,
  selected,
  onChange,
}: {
  options: string[]
  selected: string[]
  onChange: (v: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const visible = options.filter(o => o.toLowerCase().includes(search.toLowerCase()))
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])

  return (
    <div className="space-y-1">
      {options.length > 8 && (
        <input
          className="w-full bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600 mb-1"
          placeholder="Search…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onClick={e => e.stopPropagation()}
        />
      )}
      <div className="max-h-48 overflow-y-auto space-y-0.5">
        {visible.map(opt => (
          <label key={opt} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-gray-700 cursor-pointer">
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              onChange={() => toggle(opt)}
              className="accent-blue-500"
            />
            <span className="text-xs text-gray-200">{opt}</span>
          </label>
        ))}
        {visible.length === 0 && (
          <p className="text-xs text-gray-500 px-1">No matches</p>
        )}
      </div>
      {selected.length > 0 && (
        <button
          onClick={() => onChange([])}
          className="text-xs text-red-400 hover:text-red-300 mt-1"
        >
          Clear ({selected.length})
        </button>
      )}
    </div>
  )
}

function RangeInputs({
  value,
  onChange,
  prefix = '',
}: {
  value: RangeFilter
  onChange: (v: RangeFilter) => void
  prefix?: string
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-gray-500 w-7">Min</span>
        <input
          type="number"
          className="flex-1 bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600"
          placeholder={prefix ? `${prefix}0` : '0'}
          value={value.min}
          onChange={e => onChange({ ...value, min: e.target.value })}
          onClick={e => e.stopPropagation()}
        />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-gray-500 w-7">Max</span>
        <input
          type="number"
          className="flex-1 bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600"
          placeholder="∞"
          value={value.max}
          onChange={e => onChange({ ...value, max: e.target.value })}
          onClick={e => e.stopPropagation()}
        />
      </div>
      {(value.min || value.max) && (
        <button
          onClick={() => onChange({ min: '', max: '' })}
          className="text-xs text-red-400 hover:text-red-300"
        >
          Clear
        </button>
      )}
    </div>
  )
}

interface DropdownProps {
  colKey: string
  isOpen: boolean
  onClose: () => void
  filters: ColFilters
  onFiltersChange: (f: ColFilters) => void
  facets: { states: string[]; cities: string[]; flag_counts: number[]; active_months: number[] } | undefined
  anchorRef: React.RefObject<HTMLButtonElement>
}

function FilterDropdown({ colKey, isOpen, onClose, filters, onFiltersChange, facets, anchorRef }: DropdownProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  useEffect(() => {
    if (isOpen && anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect()
      setPos({ top: rect.bottom + 4, left: rect.left })
    }
  }, [isOpen, anchorRef])

  useEffect(() => {
    if (!isOpen) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node) &&
          anchorRef.current && !anchorRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen, onClose, anchorRef])

  if (!isOpen) return null

  const FLAG_OPTIONS = ['0', '1', '2', '3+']

  const content = (() => {
    switch (colKey) {
      case 'state':
        return (
          <CheckboxList
            options={facets?.states ?? []}
            selected={filters.states}
            onChange={v => onFiltersChange({ ...filters, states: v })}
          />
        )
      case 'city':
        return (
          <CheckboxList
            options={facets?.cities ?? []}
            selected={filters.cities}
            onChange={v => onFiltersChange({ ...filters, cities: v })}
          />
        )
      case 'flag_count':
        return (
          <CheckboxList
            options={FLAG_OPTIONS}
            selected={filters.flag_counts}
            onChange={v => onFiltersChange({ ...filters, flag_counts: v })}
          />
        )
      case 'risk_score':
        return <RangeInputs value={filters.risk} onChange={v => onFiltersChange({ ...filters, risk: v })} />
      case 'total_paid':
        return <RangeInputs value={filters.total_paid} onChange={v => onFiltersChange({ ...filters, total_paid: v })} prefix="$" />
      case 'total_claims':
        return <RangeInputs value={filters.total_claims} onChange={v => onFiltersChange({ ...filters, total_claims: v })} />
      case 'active_months':
        return <RangeInputs value={filters.active_months} onChange={v => onFiltersChange({ ...filters, active_months: v })} />
      default:
        return <p className="text-xs text-gray-500">No filter for this column</p>
    }
  })()

  return (
    <div
      ref={panelRef}
      className="fixed z-50 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-3 min-w-[180px]"
      style={{ top: pos.top, left: pos.left }}
      onClick={e => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Filter</span>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xs">✕</button>
      </div>
      {content}
    </div>
  )
}

// ── Column header cell ────────────────────────────────────────────────────────

interface ColDef {
  key: string
  label: string
  filterable?: boolean
}

const STATUS_COLORS: Record<string, string> = {
  pending:        'text-yellow-400 bg-yellow-400/10',
  reviewed:       'text-blue-400 bg-blue-400/10',
  confirmed_fraud:'text-red-400 bg-red-400/10',
  dismissed:      'text-gray-500 bg-gray-500/10',
}
const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending', reviewed: 'Reviewed', confirmed_fraud: 'Fraud', dismissed: 'Dismissed',
}

const COLUMNS: ColDef[] = [
  { key: 'npi',                 label: 'NPI' },
  { key: 'provider_name',       label: 'Name' },
  { key: 'oig_excluded',        label: 'OIG' },
  { key: 'risk_score',          label: 'Risk Score',   filterable: true },
  { key: 'flag_count',          label: 'Flags',        filterable: true },
  { key: 'state',               label: 'State',        filterable: true },
  { key: 'city',                label: 'City',         filterable: true },
  { key: 'total_paid',          label: 'Total Paid',   filterable: true },
  { key: 'total_claims',        label: 'Claims',       filterable: true },
  { key: 'total_beneficiaries', label: 'Beneficiaries' },
  { key: 'active_months',       label: 'Mo. Active',   filterable: true },
  { key: 'review_status',       label: 'Review' },
]

function ColHeader({
  col,
  sortBy,
  sortDir,
  onSort,
  openFilter,
  onOpenFilterChange,
  activeFilter,
  filters,
  onFiltersChange,
  facets,
}: {
  col: ColDef
  sortBy: string
  sortDir: SortDir
  onSort: (key: string) => void
  openFilter: string | null
  onOpenFilterChange: (key: string | null) => void
  activeFilter: boolean
  filters: ColFilters
  onFiltersChange: (f: ColFilters) => void
  facets: any
}) {
  const btnRef = useRef<HTMLButtonElement>(null!)
  const isOpen = openFilter === col.key
  const isSorted = sortBy === col.key

  return (
    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider select-none">
      <div className="flex items-center gap-1">
        <button
          className="flex items-center gap-0.5 hover:text-gray-300 transition-colors"
          onClick={() => onSort(col.key)}
        >
          {col.label}
          {isSorted
            ? <span className="text-blue-400 ml-0.5">{sortDir === 'asc' ? '▲' : '▼'}</span>
            : <span className="text-gray-700 ml-0.5">⇅</span>
          }
        </button>
        {col.filterable && (
          <>
            <button
              ref={btnRef}
              onClick={e => { e.stopPropagation(); onOpenFilterChange(isOpen ? null : col.key) }}
              title="Filter"
              className={`ml-0.5 text-xs transition-colors ${activeFilter ? 'text-blue-400' : 'text-gray-600 hover:text-gray-400'}`}
            >
              {activeFilter ? '⬛' : '▽'}
            </button>
            <FilterDropdown
              colKey={col.key}
              isOpen={isOpen}
              onClose={() => onOpenFilterChange(null)}
              filters={filters}
              onFiltersChange={onFiltersChange}
              facets={facets}
              anchorRef={btnRef}
            />
          </>
        )}
      </div>
    </th>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const LIMIT = 50

export default function ProviderExplorer() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const stateParam = searchParams.get('state')
  const riskMinParam = searchParams.get('risk_min')
  const [search, setSearch]       = useState('')
  const [page, setPage]           = useState(1)
  const [sortBy, setSortBy]       = useState('risk_score')
  const [sortDir, setSortDir]     = useState<SortDir>('desc')
  const [filters, setFilters]     = useState<ColFilters>(() => {
    const f = { ...EMPTY_FILTERS }
    if (stateParam) f.states = [stateParam]
    if (riskMinParam) f.risk = { ...f.risk, min: riskMinParam }
    return f
  })
  const [openFilter, setOpenFilter] = useState<string | null>(null)
  const [focusedRow, setFocusedRow] = useState<number>(-1)

  // Clear URL params after consuming them so they don't stick on navigation
  useEffect(() => {
    if (stateParam || riskMinParam) {
      searchParams.delete('state')
      searchParams.delete('risk_min')
      setSearchParams(searchParams, { replace: true })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { data: facets } = useQuery({
    queryKey: ['provider-facets'],
    queryFn: api.providerFacets,
    staleTime: 30_000,
  })

  // Build query params from filter state
  const queryParams = useCallback(() => {
    const p: Record<string, string | number> = {
      sort_by:  sortBy,
      sort_dir: sortDir,
      page,
      limit:    LIMIT,
    }
    if (search)                    p.search = search
    if (filters.states.length)     p.states = filters.states.join(',')
    if (filters.cities.length)     p.cities = filters.cities.join(',')
    if (filters.flag_counts.length) p.flag_counts = filters.flag_counts.join(',')
    if (filters.risk.min)          p.min_risk = Number(filters.risk.min)
    if (filters.risk.max)          p.max_risk = Number(filters.risk.max)
    if (filters.total_paid.min)    p.min_paid = Number(filters.total_paid.min)
    if (filters.total_paid.max)    p.max_paid = Number(filters.total_paid.max)
    if (filters.total_claims.min)  p.min_claims = Number(filters.total_claims.min)
    if (filters.total_claims.max)  p.max_claims = Number(filters.total_claims.max)
    if (filters.active_months.min) p.min_months = Number(filters.active_months.min)
    if (filters.active_months.max) p.max_months = Number(filters.active_months.max)
    return p
  }, [search, sortBy, sortDir, page, filters])

  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ['providers', queryParams()],
    queryFn: () => api.providers(queryParams() as any),
    refetchInterval: 30000,
  })

  const lastUpdated = useMemo(() => {
    if (!dataUpdatedAt) return null
    return new Date(dataUpdatedAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }, [dataUpdatedAt])

  function handleSort(key: string) {
    if (sortBy === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(key)
      setSortDir('desc')
    }
    setPage(1)
  }

  function handleFiltersChange(f: ColFilters) {
    setFilters(f)
    setPage(1)
  }

  function handleClearAll() {
    setSearch('')
    setFilters(EMPTY_FILTERS)
    setPage(1)
  }

  const providers  = data?.providers ?? []
  const total      = data?.total ?? 0
  const totalPages = total > 0 ? Math.ceil(total / LIMIT) : 1
  const anyFilter  = !!search || hasFilter(filters)

  // Keyboard navigation: j/k to move, Enter to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedRow(r => Math.min(providers.length - 1, r + 1))
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusedRow(r => Math.max(0, r - 1))
      } else if (e.key === 'Enter' && focusedRow >= 0 && focusedRow < providers.length) {
        navigate(`/providers/${providers[focusedRow].npi}`)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [providers, focusedRow, navigate])

  // ── CSV export ────────────────────────────────────────────────────────────
  const handleExportCSV = () => {
    window.open('/api/providers/export/csv', '_blank')
  }

  // ── Saved searches ──────────────────────────────────────────────────────
  const [savedSearchOpen, setSavedSearchOpen] = useState(false)
  const [savedSearchName, setSavedSearchName] = useState('')
  const savedSearchRef = useRef<HTMLDivElement>(null)

  const { data: savedSearches, refetch: refetchSaved } = useQuery({
    queryKey: ['saved-searches'],
    queryFn: () => get<{ searches: any[] }>('/saved-searches').catch(() => ({ searches: [] })),
    staleTime: 10_000,
  })

  useClickOutside(savedSearchRef, useCallback(() => setSavedSearchOpen(false), []))

  const handleSaveSearch = async () => {
    if (!savedSearchName.trim()) return
    await mutate<{ ok: boolean }>('POST', '/saved-searches', { name: savedSearchName.trim(), filters: { ...filters, search } })
    setSavedSearchName('')
    refetchSaved()
  }

  const handleLoadSearch = (saved: any) => {
    const f = saved.filters || {}
    setFilters({
      states: f.states || [],
      cities: f.cities || [],
      flag_counts: f.flag_counts || [],
      risk: f.risk || { min: '', max: '' },
      total_paid: f.total_paid || { min: '', max: '' },
      total_claims: f.total_claims || { min: '', max: '' },
      active_months: f.active_months || { min: '', max: '' },
    })
    if (f.search) setSearch(f.search)
    setPage(1)
    setSavedSearchOpen(false)
  }

  const handleDeleteSearch = async (id: string) => {
    await mutate<{ ok: boolean }>('DELETE', `/saved-searches/${id}`)
    refetchSaved()
  }

  return (
    <div className="space-y-4" onClick={() => setOpenFilter(null)}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-2xl font-bold text-white">Provider Explorer</h1>
        <div className="flex items-center gap-2">
          {anyFilter && (
            <button onClick={handleClearAll} className="text-sm text-red-400 hover:text-red-300">
              Clear all filters
            </button>
          )}
          {/* Saved searches dropdown */}
          <div className="relative" ref={savedSearchRef}>
            <button
              onClick={(e) => { e.stopPropagation(); setSavedSearchOpen(!savedSearchOpen) }}
              className="btn-ghost text-sm flex items-center gap-1"
              aria-label="Saved searches"
            >
              Saved Searches
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {savedSearchOpen && (
              <div className="absolute top-full right-0 mt-1 w-64 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 p-3" onClick={e => e.stopPropagation()}>
                <div className="flex gap-1 mb-2">
                  <input
                    className="flex-1 bg-gray-700 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                    placeholder="Save current filters as..."
                    value={savedSearchName}
                    onChange={e => setSavedSearchName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleSaveSearch() }}
                  />
                  <button
                    onClick={handleSaveSearch}
                    disabled={!savedSearchName.trim()}
                    className="btn-primary text-xs py-1"
                  >
                    Save
                  </button>
                </div>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {(savedSearches?.searches ?? []).length === 0 ? (
                    <p className="text-xs text-gray-500 text-center py-2">No saved searches</p>
                  ) : (
                    (savedSearches?.searches ?? []).map((s: any) => (
                      <div
                        key={s.id}
                        className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-gray-700 cursor-pointer group"
                      >
                        <button
                          onClick={() => handleLoadSearch(s)}
                          className="text-xs text-gray-300 hover:text-white text-left flex-1 truncate"
                        >
                          {s.name}
                        </button>
                        <button
                          onClick={() => handleDeleteSearch(s.id)}
                          className="text-xs text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 ml-2"
                          aria-label={`Delete search ${s.name}`}
                        >
                          x
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
          <button
            onClick={handleExportCSV}
            className="btn-ghost text-sm flex items-center gap-1"
            aria-label="Export providers to CSV"
          >
            Export CSV
          </button>
        </div>
      </div>

      {/* Search bar */}
      <div className="card flex flex-wrap gap-3 items-center py-3">
        <input
          className="input flex-1 max-w-sm"
          placeholder="Search by NPI or provider name…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
        />
        {anyFilter && (
          <span className="text-xs text-blue-400 font-medium">
            {total.toLocaleString()} results after filters
          </span>
        )}
        <span className="ml-auto text-xs text-gray-600 hidden sm:block">
          j/k or ↑/↓ to navigate · Enter to open
        </span>
      </div>

      {/* Summary row */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-gray-500">
          {!isLoading && total > 0 && `Showing ${Math.min(providers.length, LIMIT)} of ${total.toLocaleString()} providers`}
        </span>
        {lastUpdated && (
          <span className="text-xs text-gray-600">
            Last updated {lastUpdated}
          </span>
        )}
      </div>

      {/* Table */}
      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm whitespace-nowrap">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/80">
              {COLUMNS.map(col => (
                <ColHeader
                  key={col.key}
                  col={col}
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                  openFilter={openFilter}
                  onOpenFilterChange={setOpenFilter}
                  activeFilter={colHasFilter(col.key, filters)}
                  filters={filters}
                  onFiltersChange={handleFiltersChange}
                  facets={facets}
                />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {isLoading && (
              <tr>
                <td colSpan={COLUMNS.length} className="p-0">
                  <SkeletonTable rows={10} columns={COLUMNS.length} />
                </td>
              </tr>
            )}
            {error && (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-8 text-center text-red-400">
                  {String(error)}
                </td>
              </tr>
            )}
            {providers.map((p, idx) => {
              const name     = p.provider_name || (p as any).nppes?.name || ''
              const cityVal  = p.city || (p as any).nppes?.address?.city || ''
              const stateVal = p.state || (p as any).nppes?.address?.state || ''
              const isFocused = focusedRow === idx
              const reviewStatus = (p as any).review_status as string | undefined
              const isHighRisk = p.risk_score >= 50
              return (
                <tr
                  key={p.npi}
                  className={`cursor-pointer transition-colors ${
                    isFocused
                      ? 'bg-blue-900/30 outline outline-1 outline-blue-600'
                      : isHighRisk
                        ? 'bg-red-950/30 hover:bg-red-950/50'
                        : idx % 2 === 1
                          ? 'bg-gray-900/30 hover:bg-gray-800/50'
                          : 'hover:bg-gray-800/50'
                  }`}
                  onClick={() => navigate(`/providers/${p.npi}`)}
                  onMouseEnter={() => setFocusedRow(idx)}
                >
                  <td className="px-3 py-2.5 font-mono-data text-blue-400 text-xs">{p.npi}</td>
                  <td className="px-3 py-2.5 text-gray-300 max-w-[200px] truncate" title={name}>
                    {name || <span className="text-gray-600 italic">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    {(p as any).oig_excluded
                      ? <span className="text-xs px-1.5 py-0.5 rounded font-bold bg-red-900/60 text-red-300 border border-red-700" title={(p as any).oig_detail?.excl_type || 'OIG Excluded'}>EXCLUDED</span>
                      : <span className="text-gray-700 text-xs">—</span>
                    }
                  </td>
                  <td className="px-3 py-2.5"><RiskScoreBadge score={p.risk_score} size="sm" /></td>
                  <td className="px-3 py-2.5">
                    {p.flags.length > 0
                      ? <span className="text-red-400 text-xs font-medium">{'\u26A0'} {p.flags.length} flag{p.flags.length !== 1 ? 's' : ''}</span>
                      : <span className="text-gray-600 text-xs">—</span>
                    }
                  </td>
                  <td className="px-3 py-2.5 text-gray-400">{stateVal || <span className="text-gray-600">—</span>}</td>
                  <td className="px-3 py-2.5 text-gray-400 max-w-[140px] truncate" title={cityVal}>
                    {cityVal || <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-3 py-2.5 font-semibold">{fmt(p.total_paid)}</td>
                  <td className="px-3 py-2.5 text-gray-400">{p.total_claims.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-gray-400">{p.total_beneficiaries.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-gray-400">{p.active_months}</td>
                  <td className="px-3 py-2.5">
                    {reviewStatus
                      ? <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${STATUS_COLORS[reviewStatus] ?? 'text-gray-400'}`}>
                          {STATUS_LABELS[reviewStatus] ?? reviewStatus}
                        </span>
                      : <span className="text-gray-700 text-xs">—</span>
                    }
                  </td>
                </tr>
              )
            })}
            {!isLoading && providers.length === 0 && !error && (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-8 text-center text-gray-500">
                  No results. Try adjusting your filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <span className="text-gray-500 text-sm">
          {total > 0 ? `${total.toLocaleString()} providers` : ''}
        </span>
        <div className="flex items-center gap-3">
          <button
            className="btn-ghost"
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
          >
            ← Prev
          </button>
          <span className="text-gray-300 text-sm font-mono bg-gray-800 px-3 py-1 rounded">
            {page} / {totalPages}
          </span>
          <button
            className="btn-ghost"
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  )
}
