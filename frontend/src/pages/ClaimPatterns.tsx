import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { fmt } from '../lib/format'

// ── Types ────────────────────────────────────────────────────────────────────

interface SeverityCounts {
  CRITICAL: number
  HIGH: number
  MEDIUM: number
}

interface PatternSummaryCategory {
  count: number
  total_paid: number
  severity_counts: SeverityCounts
}

interface PatternSummary {
  unbundling: PatternSummaryCategory
  duplicates: PatternSummaryCategory
  pos_violations: PatternSummaryCategory
  modifier_abuse: PatternSummaryCategory
  impossible_days: PatternSummaryCategory
  total_patterns: number
}

interface UnbundlingPattern {
  npi: string
  bundle_name: string
  bundled_code: string
  component_count: number
  component_claims: number
  component_paid: number
  bundled_claims: number
  unbundling_rate: number
  codes_billed: string[]
  description: string
  severity: string
}

interface DuplicatePattern {
  npi: string
  duplicate_clusters: number
  total_duplicate_lines: number
  duplicate_paid: number
  max_occurrences: number
  affected_codes: string[]
  all_paid: number
  duplicate_rate: number
  severity: string
}

interface PosViolation {
  npi: string
  surgical_code_count: number
  surgical_claims: number
  surgical_paid: number
  surgical_codes: string[]
  office_em_claims: number
  total_claims: number
  total_paid: number
  surgical_ratio: number
  office_ratio: number
  violation_type: string
  severity: string
}

interface ModifierAbuse {
  npi: string
  em_claims: number
  em_paid: number
  proc_claims: number
  proc_paid: number
  total_claims: number
  total_paid: number
  em_rate: number
  proc_to_em_ratio: number
  combo_share: number
  modifier_patterns: string[]
  severity: string
}

interface ImpossibleDay {
  npi: string
  impossible_months: number
  max_benes_per_day: number
  max_claims_per_day: number
  max_hours_per_day: number
  impossible_paid: number
  worst_months: string[]
  total_paid: number
  total_claims: number
  active_months: number
  impossible_rate: number
  severity: string
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const pct = (n: number) => `${(n * 100).toFixed(1)}%`

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    CRITICAL: 'bg-red-900/60 text-red-300 border-red-700',
    HIGH: 'bg-orange-900/60 text-orange-300 border-orange-700',
    MEDIUM: 'bg-yellow-900/60 text-yellow-300 border-yellow-700',
    LOW: 'bg-blue-900/60 text-blue-300 border-blue-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${colors[severity] || colors.LOW}`}>
      {severity}
    </span>
  )
}

function NpiLink({ npi }: { npi: string }) {
  return (
    <Link to={`/providers/${npi}`} className="text-blue-400 hover:text-blue-300 font-mono text-sm">
      {npi}
    </Link>
  )
}

// ── Tab definitions ─────────────────────────────────────────────────────────

const TABS = [
  { id: 'unbundling', label: 'Unbundling', icon: 'U' },
  { id: 'duplicates', label: 'Duplicates', icon: 'D' },
  { id: 'pos', label: 'Place of Service', icon: 'P' },
  { id: 'modifiers', label: 'Modifiers', icon: 'M' },
  { id: 'impossible', label: 'Impossible Days', icon: 'I' },
] as const

type TabId = (typeof TABS)[number]['id']

// ── KPI Card ────────────────────────────────────────────────────────────────

function KpiCard({
  title,
  count,
  total_paid,
  severity_counts,
  active,
  onClick,
}: PatternSummaryCategory & { title: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`text-left rounded-xl border p-4 transition-all ${
        active
          ? 'border-blue-500 bg-blue-950/40 shadow-lg shadow-blue-900/20'
          : 'border-gray-700 bg-gray-800/60 hover:border-gray-600'
      }`}
    >
      <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">{title}</div>
      <div className="text-2xl font-bold text-white">{count}</div>
      <div className="text-xs text-gray-500 mt-1">{fmt(total_paid)} at risk</div>
      <div className="flex gap-2 mt-2">
        {severity_counts.CRITICAL > 0 && (
          <span className="text-xs text-red-400">{severity_counts.CRITICAL} critical</span>
        )}
        {severity_counts.HIGH > 0 && (
          <span className="text-xs text-orange-400">{severity_counts.HIGH} high</span>
        )}
      </div>
    </button>
  )
}

// ── Tab content components ──────────────────────────────────────────────────

function UnbundlingTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['claim-patterns', 'unbundling'],
    queryFn: () => api.claimPatternUnbundling(),
  })
  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading unbundling patterns...</div>
  const patterns = (data as any)?.patterns as UnbundlingPattern[] ?? []
  if (!patterns.length) return <div className="text-gray-500 py-8 text-center">No unbundling patterns detected</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-700">
            <th className="py-2 px-3">NPI</th>
            <th className="py-2 px-3">Bundle</th>
            <th className="py-2 px-3">Components</th>
            <th className="py-2 px-3 text-right">Comp. Claims</th>
            <th className="py-2 px-3 text-right">Bundled Claims</th>
            <th className="py-2 px-3 text-right">Unbundling Rate</th>
            <th className="py-2 px-3 text-right">$ at Risk</th>
            <th className="py-2 px-3">Severity</th>
          </tr>
        </thead>
        <tbody>
          {patterns.map((p, i) => (
            <tr key={`${p.npi}-${p.bundle_name}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-2 px-3"><NpiLink npi={p.npi} /></td>
              <td className="py-2 px-3">
                <div className="text-white font-medium">{p.bundle_name}</div>
                <div className="text-xs text-gray-500">Bundled: {p.bundled_code}</div>
              </td>
              <td className="py-2 px-3">
                <div className="text-white">{p.component_count} codes</div>
                <div className="text-xs text-gray-500 font-mono">{p.codes_billed.slice(0, 5).join(', ')}</div>
              </td>
              <td className="py-2 px-3 text-right text-white">{p.component_claims.toLocaleString()}</td>
              <td className="py-2 px-3 text-right text-white">{p.bundled_claims.toLocaleString()}</td>
              <td className="py-2 px-3 text-right text-white font-semibold">{pct(p.unbundling_rate)}</td>
              <td className="py-2 px-3 text-right text-white">{fmt(p.component_paid)}</td>
              <td className="py-2 px-3"><SeverityBadge severity={p.severity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DuplicatesTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['claim-patterns', 'duplicates'],
    queryFn: () => api.claimPatternDuplicates(),
  })
  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading duplicate patterns...</div>
  const patterns = (data as any)?.patterns as DuplicatePattern[] ?? []
  if (!patterns.length) return <div className="text-gray-500 py-8 text-center">No duplicate patterns detected</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-700">
            <th className="py-2 px-3">NPI</th>
            <th className="py-2 px-3 text-right">Dup Clusters</th>
            <th className="py-2 px-3 text-right">Dup Lines</th>
            <th className="py-2 px-3 text-right">Max Repeats</th>
            <th className="py-2 px-3 text-right">Dup Rate</th>
            <th className="py-2 px-3 text-right">$ Duplicated</th>
            <th className="py-2 px-3 text-right">Total Paid</th>
            <th className="py-2 px-3">Affected Codes</th>
            <th className="py-2 px-3">Severity</th>
          </tr>
        </thead>
        <tbody>
          {patterns.map((p, i) => (
            <tr key={`${p.npi}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-2 px-3"><NpiLink npi={p.npi} /></td>
              <td className="py-2 px-3 text-right text-white">{p.duplicate_clusters}</td>
              <td className="py-2 px-3 text-right text-white">{p.total_duplicate_lines}</td>
              <td className="py-2 px-3 text-right text-white font-semibold">{p.max_occurrences}x</td>
              <td className="py-2 px-3 text-right text-white">{pct(p.duplicate_rate)}</td>
              <td className="py-2 px-3 text-right text-red-400 font-semibold">{fmt(p.duplicate_paid)}</td>
              <td className="py-2 px-3 text-right text-white">{fmt(p.all_paid)}</td>
              <td className="py-2 px-3">
                <span className="text-xs text-gray-400 font-mono">{p.affected_codes.slice(0, 5).join(', ')}</span>
              </td>
              <td className="py-2 px-3"><SeverityBadge severity={p.severity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PosTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['claim-patterns', 'pos'],
    queryFn: () => api.claimPatternPos(),
  })
  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading place-of-service patterns...</div>
  const patterns = (data as any)?.patterns as PosViolation[] ?? []
  if (!patterns.length) return <div className="text-gray-500 py-8 text-center">No place-of-service violations detected</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-700">
            <th className="py-2 px-3">NPI</th>
            <th className="py-2 px-3 text-right">Surgical Codes</th>
            <th className="py-2 px-3 text-right">Surgical Claims</th>
            <th className="py-2 px-3 text-right">Surgical Ratio</th>
            <th className="py-2 px-3 text-right">Office E&M Claims</th>
            <th className="py-2 px-3 text-right">$ Surgical</th>
            <th className="py-2 px-3 text-right">$ Total</th>
            <th className="py-2 px-3">Top Codes</th>
            <th className="py-2 px-3">Severity</th>
          </tr>
        </thead>
        <tbody>
          {patterns.map((p, i) => (
            <tr key={`${p.npi}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-2 px-3"><NpiLink npi={p.npi} /></td>
              <td className="py-2 px-3 text-right text-white">{p.surgical_code_count}</td>
              <td className="py-2 px-3 text-right text-white">{p.surgical_claims.toLocaleString()}</td>
              <td className="py-2 px-3 text-right text-white font-semibold">{pct(p.surgical_ratio)}</td>
              <td className="py-2 px-3 text-right text-white">{p.office_em_claims.toLocaleString()}</td>
              <td className="py-2 px-3 text-right text-red-400 font-semibold">{fmt(p.surgical_paid)}</td>
              <td className="py-2 px-3 text-right text-white">{fmt(p.total_paid)}</td>
              <td className="py-2 px-3">
                <span className="text-xs text-gray-400 font-mono">{p.surgical_codes.slice(0, 4).join(', ')}</span>
              </td>
              <td className="py-2 px-3"><SeverityBadge severity={p.severity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ModifiersTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['claim-patterns', 'modifiers'],
    queryFn: () => api.claimPatternModifiers(),
  })
  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading modifier patterns...</div>
  const patterns = (data as any)?.patterns as ModifierAbuse[] ?? []
  if (!patterns.length) return <div className="text-gray-500 py-8 text-center">No modifier abuse patterns detected</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-700">
            <th className="py-2 px-3">NPI</th>
            <th className="py-2 px-3 text-right">E&M Claims</th>
            <th className="py-2 px-3 text-right">Proc Claims</th>
            <th className="py-2 px-3 text-right">Proc/E&M Ratio</th>
            <th className="py-2 px-3 text-right">E&M Rate</th>
            <th className="py-2 px-3 text-right">Combo Share</th>
            <th className="py-2 px-3 text-right">$ Total</th>
            <th className="py-2 px-3">Patterns</th>
            <th className="py-2 px-3">Severity</th>
          </tr>
        </thead>
        <tbody>
          {patterns.map((p, i) => (
            <tr key={`${p.npi}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-2 px-3"><NpiLink npi={p.npi} /></td>
              <td className="py-2 px-3 text-right text-white">{p.em_claims.toLocaleString()}</td>
              <td className="py-2 px-3 text-right text-white">{p.proc_claims.toLocaleString()}</td>
              <td className="py-2 px-3 text-right text-white font-semibold">{pct(p.proc_to_em_ratio)}</td>
              <td className="py-2 px-3 text-right text-white">{pct(p.em_rate)}</td>
              <td className="py-2 px-3 text-right text-white">{pct(p.combo_share)}</td>
              <td className="py-2 px-3 text-right text-white">{fmt(p.total_paid)}</td>
              <td className="py-2 px-3">
                {p.modifier_patterns.map((mp, j) => (
                  <span key={j} className="inline-block mr-1 mb-1 px-2 py-0.5 bg-purple-900/40 text-purple-300 border border-purple-700 rounded text-xs">
                    {mp}
                  </span>
                ))}
              </td>
              <td className="py-2 px-3"><SeverityBadge severity={p.severity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ImpossibleTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['claim-patterns', 'impossible'],
    queryFn: () => api.claimPatternImpossible(),
  })
  if (isLoading) return <div className="text-gray-400 py-8 text-center">Loading impossible day patterns...</div>
  const patterns = (data as any)?.patterns as ImpossibleDay[] ?? []
  if (!patterns.length) return <div className="text-gray-500 py-8 text-center">No impossible day patterns detected</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-700">
            <th className="py-2 px-3">NPI</th>
            <th className="py-2 px-3 text-right">Impossible Months</th>
            <th className="py-2 px-3 text-right">Max Benes/Day</th>
            <th className="py-2 px-3 text-right">Max Claims/Day</th>
            <th className="py-2 px-3 text-right">Max Hours/Day</th>
            <th className="py-2 px-3 text-right">Impossible Rate</th>
            <th className="py-2 px-3 text-right">$ at Risk</th>
            <th className="py-2 px-3">Worst Months</th>
            <th className="py-2 px-3">Severity</th>
          </tr>
        </thead>
        <tbody>
          {patterns.map((p, i) => (
            <tr key={`${p.npi}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/50">
              <td className="py-2 px-3"><NpiLink npi={p.npi} /></td>
              <td className="py-2 px-3 text-right text-white">{p.impossible_months}</td>
              <td className="py-2 px-3 text-right text-red-400 font-bold">{p.max_benes_per_day}</td>
              <td className="py-2 px-3 text-right text-white">{p.max_claims_per_day}</td>
              <td className="py-2 px-3 text-right text-white">
                {p.max_hours_per_day > 24 ? (
                  <span className="text-red-400 font-bold">{p.max_hours_per_day}h</span>
                ) : (
                  `${p.max_hours_per_day}h`
                )}
              </td>
              <td className="py-2 px-3 text-right text-white">{pct(p.impossible_rate)}</td>
              <td className="py-2 px-3 text-right text-red-400 font-semibold">{fmt(p.impossible_paid)}</td>
              <td className="py-2 px-3">
                <span className="text-xs text-gray-400">{p.worst_months.slice(0, 3).join(', ')}</span>
              </td>
              <td className="py-2 px-3"><SeverityBadge severity={p.severity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function ClaimPatterns() {
  const [tab, setTab] = useState<TabId>('unbundling')

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['claim-patterns', 'summary'],
    queryFn: () => api.claimPatternSummary(),
  })

  const s = summary as PatternSummary | undefined

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Claim-Level Fraud Patterns</h1>
        <p className="text-sm text-gray-400 mt-1">
          Detects unbundling, duplicate claims, place-of-service violations, modifier abuse, and impossible billing volumes
        </p>
      </div>

      {/* KPI Cards */}
      {summaryLoading ? (
        <div className="text-gray-400 text-center py-4">Loading summary...</div>
      ) : s ? (
        <>
          <div className="flex items-center gap-3 mb-2">
            <span className="text-sm text-gray-400">Total patterns detected:</span>
            <span className="text-lg font-bold text-white">{s.total_patterns.toLocaleString()}</span>
          </div>
          <div className="grid grid-cols-5 gap-4">
            <KpiCard
              title="Unbundling"
              active={tab === 'unbundling'}
              onClick={() => setTab('unbundling')}
              {...s.unbundling}
            />
            <KpiCard
              title="Duplicates"
              active={tab === 'duplicates'}
              onClick={() => setTab('duplicates')}
              {...s.duplicates}
            />
            <KpiCard
              title="Place of Service"
              active={tab === 'pos'}
              onClick={() => setTab('pos')}
              {...s.pos_violations}
            />
            <KpiCard
              title="Modifier Abuse"
              active={tab === 'modifiers'}
              onClick={() => setTab('modifiers')}
              {...s.modifier_abuse}
            />
            <KpiCard
              title="Impossible Days"
              active={tab === 'impossible'}
              onClick={() => setTab('impossible')}
              {...s.impossible_days}
            />
          </div>
        </>
      ) : null}

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-700">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t.id
                ? 'text-blue-400 border-blue-400'
                : 'text-gray-400 border-transparent hover:text-gray-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-gray-900/50 rounded-xl border border-gray-700 p-4">
        {tab === 'unbundling' && <UnbundlingTab />}
        {tab === 'duplicates' && <DuplicatesTab />}
        {tab === 'pos' && <PosTab />}
        {tab === 'modifiers' && <ModifiersTab />}
        {tab === 'impossible' && <ImpossibleTab />}
      </div>
    </div>
  )
}
