import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { get } from '../lib/api'
import { fmt } from '../lib/format'

/* ── Types ──────────────────────────────────────────────────────────────────── */

interface CodeSearchResult {
  code: string
  total_providers: number
  providers: {
    npi: string
    provider_name: string
    provider_type: string
    state: string
    risk_score: number
    total_paid: number
    total_claims: number
    code_rank: number | null
    total_codes_billed: number
  }[]
  stats: {
    total_paid_all: number
    total_claims_all: number
    avg_paid: number
    avg_risk_score: number
    high_risk_count: number
  }
}

interface TopCode {
  code: string
  provider_count: number
  total_paid: number
  total_claims: number
  avg_risk_score: number
}

interface TopCodesResult {
  total_codes: number
  codes: TopCode[]
}

interface DiagnosisResult {
  hcpcs_code: string
  hcpcs_description: string
  diagnoses: { icd10: string; description: string }[]
  total: number
  has_crosswalk: boolean
}

interface DiagFlagProvider {
  npi: string
  provider_name: string
  state: string
  risk_score: number
  issues: {
    hcpcs_code: string
    hcpcs_description: string
    category: string
    issue: string
    total_paid: number
    total_claims: number
    expected_diagnoses: { icd10: string; description: string }[]
    valid_diagnoses_for_category: { icd10: string; description: string }[]
  }[]
  issue_count: number
  total_flagged_paid: number
}

interface DiagFlagsResult {
  flagged_providers: DiagFlagProvider[]
  total: number
  category_counts: Record<string, number>
}

/* ── Risk badge ─────────────────────────────────────────────────────────────── */

function RiskBadge({ score }: { score: number }) {
  const color =
    score >= 70
      ? 'bg-red-900/60 text-red-300 border-red-700'
      : score >= 40
        ? 'bg-yellow-900/40 text-yellow-300 border-yellow-700'
        : 'bg-green-900/40 text-green-300 border-green-700'
  return (
    <span className={`text-xs font-mono px-1.5 py-0.5 rounded border ${color}`}>
      {score.toFixed(0)}
    </span>
  )
}

/* ── Diagnosis panel (shown when a code is searched) ─────────────────────── */

function DiagnosisPanel({ code }: { code: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['billing-code-dx', code],
    queryFn: () => get<DiagnosisResult>(`/billing-codes/diagnoses/${code}`),
    enabled: !!code,
  })

  if (isLoading) return <div className="text-gray-500 text-xs animate-pulse">Loading diagnoses...</div>
  if (!data || !data.has_crosswalk) return null

  return (
    <div className="bg-gray-800/40 border border-gray-700 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-white mb-1">
        Common Diagnoses for {data.hcpcs_code}
        {data.hcpcs_description && (
          <span className="text-gray-400 font-normal ml-2">({data.hcpcs_description})</span>
        )}
      </h3>
      <p className="text-xs text-gray-500 mb-3">ICD-10 codes most frequently billed with this procedure</p>
      <div className="space-y-1.5">
        {data.diagnoses.map(dx => (
          <div key={dx.icd10} className="flex items-start gap-3 group">
            <span className="font-mono text-xs text-blue-400 bg-blue-900/30 px-2 py-0.5 rounded shrink-0 min-w-[80px] text-center">
              {dx.icd10}
            </span>
            <span className="text-sm text-gray-300">{dx.description}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Diagnosis Flags tab ─────────────────────────────────────────────────── */

function DiagnosisFlagsTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['diagnosis-flags'],
    queryFn: () => get<DiagFlagsResult>('/billing-codes/diagnosis-flags', { limit: 100 }),
  })
  const [expanded, setExpanded] = useState<string | null>(null)

  if (isLoading) return <div className="text-gray-400 py-8 text-center animate-pulse">Scanning for diagnosis-billing mismatches...</div>
  if (error) return <div className="text-red-400 py-8 text-center">Error: {(error as Error).message}</div>
  if (!data || data.total === 0) return <div className="text-gray-500 py-8 text-center">No diagnosis-billing mismatches detected.</div>

  const catEntries = Object.entries(data.category_counts).sort((a, b) => b[1] - a[1])

  return (
    <div className="space-y-4">
      {/* Category breakdown */}
      <div className="flex flex-wrap gap-2">
        {catEntries.map(([cat, count]) => (
          <span key={cat} className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-lg text-xs">
            <span className="text-gray-400">{cat}:</span>{' '}
            <span className="text-orange-400 font-bold">{count}</span>
          </span>
        ))}
        <span className="px-3 py-1.5 bg-red-900/30 border border-red-800 rounded-lg text-xs">
          <span className="text-gray-400">Total Flagged:</span>{' '}
          <span className="text-red-400 font-bold">{data.total}</span>
        </span>
      </div>

      {/* Provider list */}
      <div className="space-y-2">
        {data.flagged_providers.map(p => (
          <div key={p.npi} className="bg-gray-800/40 border border-gray-700 rounded-lg overflow-hidden">
            <div
              className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-800/60 transition-colors"
              onClick={() => setExpanded(expanded === p.npi ? null : p.npi)}
            >
              <div className="flex items-center gap-3">
                <Link
                  to={`/providers/${p.npi}`}
                  className="text-blue-400 hover:text-blue-300 text-sm font-medium"
                  onClick={e => e.stopPropagation()}
                >
                  {p.provider_name || p.npi}
                </Link>
                <span className="text-gray-600 text-xs font-mono">{p.npi}</span>
                {p.state && <span className="text-gray-600 text-xs">{p.state}</span>}
                <RiskBadge score={p.risk_score} />
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="text-orange-400">{p.issue_count} issue{p.issue_count !== 1 ? 's' : ''}</span>
                <span className="text-gray-400">{fmt(p.total_flagged_paid)} flagged</span>
                <span className="text-gray-500">{expanded === p.npi ? '\u25B2' : '\u25BC'}</span>
              </div>
            </div>

            {expanded === p.npi && (
              <div className="border-t border-gray-700 px-4 py-3 space-y-3">
                {p.issues.map((issue, i) => (
                  <div key={i} className="bg-gray-900/50 rounded-lg p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-blue-400">{issue.hcpcs_code}</span>
                        {issue.hcpcs_description && (
                          <span className="text-gray-400 text-xs">{issue.hcpcs_description}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="text-gray-400">{fmt(issue.total_paid)}</span>
                        <span className="text-gray-500">{issue.total_claims} claims</span>
                      </div>
                    </div>
                    <div className="px-2 py-1.5 bg-red-900/20 border border-red-900/40 rounded text-xs text-red-300">
                      <span className="text-red-400 font-medium">{issue.category}:</span> {issue.issue}
                    </div>
                    {issue.expected_diagnoses?.length > 0 && (
                      <div className="text-xs space-y-1">
                        <div className="text-gray-500 font-medium">Common diagnoses for this code:</div>
                        {issue.expected_diagnoses.map(dx => (
                          <div key={dx.icd10} className="flex items-center gap-2 ml-2">
                            <span className="font-mono text-blue-400">{dx.icd10}</span>
                            <span className="text-gray-400">{dx.description}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {issue.valid_diagnoses_for_category?.length > 0 && (
                      <div className="text-xs space-y-1">
                        <div className="text-gray-500 font-medium">Expected diagnosis category:</div>
                        {issue.valid_diagnoses_for_category.map(dx => (
                          <div key={dx.icd10} className="flex items-center gap-2 ml-2">
                            <span className="font-mono text-green-400">{dx.icd10}</span>
                            <span className="text-gray-400">{dx.description}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── ICD-10 Search ──────────────────────────────────────────────────────── */

function IcdSearchTab() {
  const [input, setInput] = useState('')
  const [searchQ, setSearchQ] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['icd10-search', searchQ],
    queryFn: () => get<{ query: string; results: { icd10: string; description: string }[]; total: number }>(
      '/billing-codes/icd10/search', { q: searchQ, limit: 50 }
    ),
    enabled: !!searchQ,
  })

  return (
    <div className="space-y-4">
      <div className="flex gap-2 items-center">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && input.trim()) setSearchQ(input.trim()) }}
          placeholder="Search by ICD-10 code or keyword (e.g. E11, diabetes, hypertension)"
          className="flex-1 max-w-lg bg-gray-800 text-white px-4 py-2.5 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
        />
        <button
          onClick={() => input.trim() && setSearchQ(input.trim())}
          className="btn-primary px-5 py-2.5"
          disabled={!input.trim()}
        >
          Search
        </button>
      </div>

      {isLoading && <div className="text-gray-400 text-sm animate-pulse">Searching...</div>}

      {data && (
        <div className="space-y-1">
          <p className="text-xs text-gray-500">{data.total} result{data.total !== 1 ? 's' : ''}</p>
          {data.results.map(dx => (
            <div key={dx.icd10} className="flex items-start gap-3 py-1.5 border-b border-gray-800/50">
              <span className="font-mono text-xs text-blue-400 bg-blue-900/30 px-2 py-0.5 rounded shrink-0 min-w-[90px] text-center">
                {dx.icd10}
              </span>
              <span className="text-sm text-gray-300">{dx.description}</span>
            </div>
          ))}
          {data.results.length === 0 && (
            <p className="text-gray-500 text-sm py-4 text-center">No ICD-10 codes match "{data.query}"</p>
          )}
        </div>
      )}

      {!searchQ && (
        <div className="text-gray-500 text-sm py-8 text-center">
          Enter an ICD-10 code prefix (e.g. E11, I10, F32) or keyword (e.g. diabetes, anxiety) to search
        </div>
      )}
    </div>
  )
}

/* ── Main component ─────────────────────────────────────────────────────────── */

type MainTab = 'search' | 'icd-lookup' | 'dx-flags'

export default function BillingCodeSearch() {
  const [input, setInput] = useState('')
  const [searchCode, setSearchCode] = useState('')
  const [sortKey, setSortKey] = useState<'total_paid' | 'risk_score' | 'total_claims'>('total_paid')
  const [sortAsc, setSortAsc] = useState(false)
  const [mainTab, setMainTab] = useState<MainTab>('search')

  const handleSearch = useCallback(() => {
    const code = input.trim().toUpperCase()
    if (code) { setSearchCode(code); setMainTab('search') }
  }, [input])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleSearch()
    },
    [handleSearch],
  )

  // Single code search
  const { data, isLoading, error } = useQuery({
    queryKey: ['billing-code-search', searchCode],
    queryFn: () => get<CodeSearchResult>('/billing-codes/search', { code: searchCode, limit: 200 }),
    enabled: !!searchCode,
  })

  // Top codes (always loaded)
  const { data: topCodes, isLoading: topLoading } = useQuery({
    queryKey: ['top-billing-codes'],
    queryFn: () => get<TopCodesResult>('/billing-codes/top-codes', { limit: 30, min_providers: 5 }),
  })

  const handleSort = (key: typeof sortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(false)
    }
  }

  const sorted = data?.providers
    ? [...data.providers].sort((a, b) => {
        const diff = a[sortKey] - b[sortKey]
        return sortAsc ? diff : -diff
      })
    : []

  const SortHeader = ({ label, field }: { label: string; field: typeof sortKey }) => (
    <th
      className="px-3 py-2 text-right cursor-pointer hover:text-blue-400 transition-colors select-none"
      onClick={() => handleSort(field)}
    >
      {label} {sortKey === field ? (sortAsc ? '\u25B2' : '\u25BC') : ''}
    </th>
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Billing Code Analysis</h1>
        <p className="text-sm text-gray-400 mt-1">
          Search HCPCS/CPT codes, look up diagnoses, and detect billing-diagnosis mismatches
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-700 pb-0">
        {([
          { key: 'search' as MainTab, label: 'Code Search' },
          { key: 'icd-lookup' as MainTab, label: 'ICD-10 Lookup' },
          { key: 'dx-flags' as MainTab, label: 'Diagnosis Flags' },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => setMainTab(t.key)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              mainTab === t.key
                ? 'text-blue-400 border-blue-400'
                : 'text-gray-400 border-transparent hover:text-white hover:border-gray-600'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Code Search tab */}
      {mainTab === 'search' && (
        <>
          {/* Search bar */}
          <div className="flex gap-2 items-center">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter HCPCS/CPT code (e.g. 99213, J1745, E0260)"
              className="flex-1 max-w-md bg-gray-800 text-white px-4 py-2.5 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none font-mono text-sm"
              aria-label="HCPCS/CPT code"
            />
            <button onClick={handleSearch} className="btn-primary px-5 py-2.5" disabled={!input.trim()}>
              Search
            </button>
          </div>

          {/* Results */}
          {isLoading && (
            <div className="text-gray-400 text-sm animate-pulse">Searching providers...</div>
          )}
          {error && (
            <div className="text-red-400 text-sm">Error: {(error as Error).message}</div>
          )}

          {data && (
            <div className="space-y-4">
              {/* Stats cards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
                  <div className="text-xs text-gray-500 uppercase">Code</div>
                  <div className="text-lg font-mono font-bold text-blue-400">{data.code}</div>
                </div>
                <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
                  <div className="text-xs text-gray-500 uppercase">Providers</div>
                  <div className="text-lg font-bold text-white">{data.total_providers.toLocaleString()}</div>
                </div>
                <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
                  <div className="text-xs text-gray-500 uppercase">Total Paid</div>
                  <div className="text-lg font-bold text-emerald-400">{fmt(data.stats.total_paid_all)}</div>
                </div>
                <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
                  <div className="text-xs text-gray-500 uppercase">Avg Risk Score</div>
                  <div className="text-lg font-bold text-white">{data.stats.avg_risk_score.toFixed(1)}</div>
                </div>
                <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
                  <div className="text-xs text-gray-500 uppercase">High Risk</div>
                  <div className="text-lg font-bold text-red-400">{data.stats.high_risk_count}</div>
                </div>
              </div>

              {/* Diagnosis panel */}
              <DiagnosisPanel code={searchCode} />

              {/* Provider table */}
              {sorted.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-gray-500 uppercase border-b border-gray-800">
                        <th className="px-3 py-2 text-left">Provider</th>
                        <th className="px-3 py-2 text-left">Type</th>
                        <th className="px-3 py-2 text-left">State</th>
                        <SortHeader label="Risk" field="risk_score" />
                        <SortHeader label="Paid" field="total_paid" />
                        <SortHeader label="Claims" field="total_claims" />
                        <th className="px-3 py-2 text-right">Code Rank</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.map(p => (
                        <tr
                          key={p.npi}
                          className="border-b border-gray-800/50 hover:bg-gray-800/40 transition-colors"
                        >
                          <td className="px-3 py-2">
                            <Link
                              to={`/providers/${p.npi}`}
                              className="text-blue-400 hover:text-blue-300 transition-colors"
                            >
                              {p.provider_name || p.npi}
                            </Link>
                            <div className="text-xs text-gray-600 font-mono">{p.npi}</div>
                          </td>
                          <td className="px-3 py-2 text-gray-400 text-xs">{p.provider_type}</td>
                          <td className="px-3 py-2 text-gray-400">{p.state}</td>
                          <td className="px-3 py-2 text-right">
                            <RiskBadge score={p.risk_score} />
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-gray-300">{fmt(p.total_paid)}</td>
                          <td className="px-3 py-2 text-right font-mono text-gray-300">
                            {p.total_claims.toLocaleString()}
                          </td>
                          <td className="px-3 py-2 text-right text-gray-500 text-xs">
                            #{p.code_rank} of {p.total_codes_billed}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-gray-500 text-sm">No providers found billing code {data.code}.</p>
              )}
            </div>
          )}

          {/* Top codes (shown when no search active) */}
          {!searchCode && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold text-white">Top Billing Codes</h2>
              <p className="text-xs text-gray-500">Most billed codes across all scanned providers (click to search)</p>
              {topLoading && <div className="text-gray-400 text-sm animate-pulse">Loading top codes...</div>}
              {topCodes && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-gray-500 uppercase border-b border-gray-800">
                        <th className="px-3 py-2 text-left">Code</th>
                        <th className="px-3 py-2 text-right">Providers</th>
                        <th className="px-3 py-2 text-right">Total Paid</th>
                        <th className="px-3 py-2 text-right">Total Claims</th>
                        <th className="px-3 py-2 text-right">Avg Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topCodes.codes.map(c => (
                        <tr
                          key={c.code}
                          className="border-b border-gray-800/50 hover:bg-gray-800/40 cursor-pointer transition-colors"
                          onClick={() => {
                            setInput(c.code)
                            setSearchCode(c.code)
                          }}
                        >
                          <td className="px-3 py-2 font-mono text-blue-400">{c.code}</td>
                          <td className="px-3 py-2 text-right text-gray-300">
                            {c.provider_count.toLocaleString()}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-gray-300">{fmt(c.total_paid)}</td>
                          <td className="px-3 py-2 text-right font-mono text-gray-300">
                            {c.total_claims.toLocaleString()}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <RiskBadge score={c.avg_risk_score} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ICD-10 Lookup tab */}
      {mainTab === 'icd-lookup' && <IcdSearchTab />}

      {/* Diagnosis Flags tab */}
      {mainTab === 'dx-flags' && <DiagnosisFlagsTab />}
    </div>
  )
}
