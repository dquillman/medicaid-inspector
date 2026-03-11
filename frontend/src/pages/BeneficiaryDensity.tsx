import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'

type SortKey = 'state' | 'medicaid_enrollment' | 'provider_count' | 'total_billing' | 'billing_per_enrollee' | 'ratio'
type SortDir = 'asc' | 'desc'

interface StateRow {
  state: string
  medicaid_enrollment: number
  provider_count: number
  total_billing: number
  total_claims: number
  billing_per_enrollee: number
  expected_billing_per_enrollee: number
  ratio: number
  flagged: boolean
}

interface CityRow {
  city: string
  provider_count: number
  total_billing: number
  total_claims: number
  billing_share_pct: number
  top_providers: { npi: string; name: string; risk_score: number; total_paid: number }[]
}

interface StateDrilldown {
  state: string
  medicaid_enrollment: number
  total_billing: number
  provider_count: number
  billing_per_enrollee: number
  cities: CityRow[]
}

// State abbreviation to name mapping
const STATE_NAMES: Record<string, string> = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
  CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia',
  FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois',
  IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana',
  ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota',
  MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada',
  NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York',
  NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma',
  OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina',
  SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont',
  VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
}

function fmtNum(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`
  return v.toLocaleString()
}

function RatioCell({ ratio }: { ratio: number }) {
  const color =
    ratio > 1.5 ? 'text-red-400 bg-red-400/10' :
    ratio > 1.0 ? 'text-yellow-400 bg-yellow-400/10' :
    'text-green-400 bg-green-400/10'
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${color}`}>
      {ratio.toFixed(2)}x
    </span>
  )
}

function FlagBadge({ flagged }: { flagged: boolean }) {
  if (!flagged) return null
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-900/60 text-red-300 border border-red-800">
      Flagged
    </span>
  )
}

function SortHeader({
  label,
  sortKey,
  currentSort,
  currentDir,
  onSort,
  className = '',
}: {
  label: string
  sortKey: SortKey
  currentSort: SortKey
  currentDir: SortDir
  onSort: (key: SortKey) => void
  className?: string
}) {
  const active = currentSort === sortKey
  return (
    <th
      className={`px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider cursor-pointer select-none hover:text-blue-400 transition-colors ${className}`}
      onClick={() => onSort(sortKey)}
    >
      {label}
      {active && (
        <span className="ml-1 text-blue-400">{currentDir === 'asc' ? '\u25B2' : '\u25BC'}</span>
      )}
    </th>
  )
}

// ── Drill-down panel ──────────────────────────────────────────────────────────

function StateDrilldownPanel({
  state,
  onClose,
}: {
  state: string
  onClose: () => void
}) {
  const { data, isLoading, isError } = useQuery<StateDrilldown>({
    queryKey: ['beneficiary-density-state', state],
    queryFn: () => api.beneficiaryDensityState(state),
  })

  return (
    <div className="card mt-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-white">
          {STATE_NAMES[state] || state} — City-Level Breakdown
        </h3>
        <button onClick={onClose} className="btn-ghost text-xs">Close</button>
      </div>

      {isLoading && <p className="text-gray-500 text-sm">Loading city data...</p>}
      {isError && <p className="text-red-400 text-sm">Failed to load state data.</p>}

      {data && (
        <>
          <div className="grid grid-cols-4 gap-3 mb-4">
            <div className="bg-gray-800/50 rounded-lg p-3">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">Enrollment</div>
              <div className="text-lg font-bold text-white">{fmtNum(data.medicaid_enrollment)}</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-3">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">Providers</div>
              <div className="text-lg font-bold text-white">{data.provider_count.toLocaleString()}</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-3">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">Total Billing</div>
              <div className="text-lg font-bold text-white">{fmt(data.total_billing)}</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-3">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">$/Enrollee</div>
              <div className="text-lg font-bold text-white">{fmt(data.billing_per_enrollee)}</div>
            </div>
          </div>

          {data.cities.length === 0 ? (
            <p className="text-gray-500 text-sm">No provider data available for this state.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800">
                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase">City</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold uppercase">Providers</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold uppercase">Billing</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold uppercase">Claims</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold uppercase">Billing Share</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase">Top Providers</th>
                  </tr>
                </thead>
                <tbody>
                  {data.cities.map((city: CityRow) => (
                    <tr key={city.city} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-3 py-2 font-medium text-white">{city.city}</td>
                      <td className="px-3 py-2 text-right text-gray-300">{city.provider_count}</td>
                      <td className="px-3 py-2 text-right font-mono text-gray-300">{fmt(city.total_billing)}</td>
                      <td className="px-3 py-2 text-right text-gray-300">{city.total_claims.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16 bg-gray-800 rounded-full h-1.5">
                            <div
                              className="h-1.5 rounded-full bg-blue-500"
                              style={{ width: `${Math.min(city.billing_share_pct, 100)}%` }}
                            />
                          </div>
                          <span className="text-gray-400 font-mono text-xs w-12 text-right">
                            {city.billing_share_pct.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {city.top_providers.slice(0, 3).map((tp) => (
                            <a
                              key={tp.npi}
                              href={`/providers/${tp.npi}`}
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-xs transition-colors"
                              title={tp.name || tp.npi}
                            >
                              <span className={`w-1.5 h-1.5 rounded-full ${tp.risk_score >= 50 ? 'bg-red-400' : tp.risk_score >= 10 ? 'bg-yellow-400' : 'bg-green-400'}`} />
                              <span className="text-gray-400 font-mono">{tp.npi}</span>
                            </a>
                          ))}
                          {city.top_providers.length > 3 && (
                            <span className="text-gray-600 text-xs">+{city.top_providers.length - 3} more</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BeneficiaryDensity() {
  const [sortKey, setSortKey] = useState<SortKey>('ratio')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [selectedState, setSelectedState] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['beneficiary-density'],
    queryFn: api.beneficiaryDensity,
    refetchInterval: 120_000,
  })

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'state' ? 'asc' : 'desc')
    }
  }

  const states: StateRow[] = data?.states ?? []

  const sorted = [...states].sort((a, b) => {
    const av = a[sortKey]
    const bv = b[sortKey]
    if (typeof av === 'string' && typeof bv === 'string') {
      return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    }
    const an = Number(av) || 0
    const bn = Number(bv) || 0
    return sortDir === 'asc' ? an - bn : bn - an
  })

  // KPI computations
  const totalEnrollment = data?.total_enrollment ?? 0
  const flaggedCount = data?.flagged_count ?? 0
  const highestRatioState = states.length > 0
    ? states.reduce((max, s) => (s.ratio > max.ratio ? s : max), states[0])
    : null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Beneficiary Density Mapping</h1>
        <p className="text-sm text-gray-500 mt-1">
          Medicaid enrollment by state vs. provider billing volume — flags areas where billing far exceeds enrolled population
        </p>
      </div>

      {isError && (
        <div className="card border-red-900 bg-red-950/30">
          <p className="text-red-400 text-sm">Failed to load beneficiary density data.</p>
        </div>
      )}

      {isLoading && (
        <div className="card">
          <p className="text-gray-500 text-sm">Loading enrollment and billing data...</p>
        </div>
      )}

      {data && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-3 gap-4">
            <div className="card">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Total Enrollment</div>
              <div className="text-2xl font-bold text-white">{fmtNum(totalEnrollment)}</div>
              <div className="text-xs text-gray-500 mt-1">{states.length} states tracked</div>
            </div>
            <div className="card">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">States Flagged</div>
              <div className="text-2xl font-bold text-red-400">{flaggedCount}</div>
              <div className="text-xs text-gray-500 mt-1">Ratio &gt; 1.5x national avg</div>
            </div>
            <div className="card">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Highest Ratio</div>
              {highestRatioState ? (
                <>
                  <div className="text-2xl font-bold text-white">
                    {STATE_NAMES[highestRatioState.state] || highestRatioState.state}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    <RatioCell ratio={highestRatioState.ratio} />
                    <span className="ml-2">{fmt(highestRatioState.billing_per_enrollee)}/enrollee</span>
                  </div>
                </>
              ) : (
                <div className="text-gray-500">No data</div>
              )}
            </div>
          </div>

          {/* State Table */}
          <div className="card">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
              State-Level Density Analysis
            </h2>
            {states.length === 0 ? (
              <p className="text-gray-500 text-sm">
                No provider data scanned yet. Run a scan from the Overview page first.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-800">
                      <SortHeader label="State" sortKey="state" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} />
                      <SortHeader label="Enrollment" sortKey="medicaid_enrollment" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} className="text-right" />
                      <SortHeader label="Providers" sortKey="provider_count" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} className="text-right" />
                      <SortHeader label="Total Billing" sortKey="total_billing" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} className="text-right" />
                      <SortHeader label="$/Enrollee" sortKey="billing_per_enrollee" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} className="text-right" />
                      <SortHeader label="Ratio vs Avg" sortKey="ratio" currentSort={sortKey} currentDir={sortDir} onSort={handleSort} className="text-right" />
                      <th className="px-3 py-2 text-center text-xs font-semibold uppercase tracking-wider text-gray-500">Flag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((s) => (
                      <tr
                        key={s.state}
                        className={`border-b border-gray-800/50 cursor-pointer transition-colors ${
                          selectedState === s.state
                            ? 'bg-blue-900/20'
                            : 'hover:bg-gray-800/30'
                        } ${s.flagged ? 'bg-red-950/10' : ''}`}
                        onClick={() => setSelectedState(selectedState === s.state ? null : s.state)}
                      >
                        <td className="px-3 py-2">
                          <span className="font-medium text-white">{s.state}</span>
                          <span className="text-gray-500 ml-1.5 text-xs">{STATE_NAMES[s.state] || ''}</span>
                        </td>
                        <td className="px-3 py-2 text-right text-gray-300 font-mono">{fmtNum(s.medicaid_enrollment)}</td>
                        <td className="px-3 py-2 text-right text-gray-300">{s.provider_count.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right text-gray-300 font-mono">{fmt(s.total_billing)}</td>
                        <td className="px-3 py-2 text-right text-gray-300 font-mono">{fmt(s.billing_per_enrollee)}</td>
                        <td className="px-3 py-2 text-right">
                          <RatioCell ratio={s.ratio} />
                        </td>
                        <td className="px-3 py-2 text-center">
                          <FlagBadge flagged={s.flagged} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Drill-down */}
          {selectedState && (
            <StateDrilldownPanel
              state={selectedState}
              onClose={() => setSelectedState(null)}
            />
          )}
        </>
      )}
    </div>
  )
}
