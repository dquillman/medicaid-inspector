import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { AlertRule, AlertCondition, AlertRuleResult } from '../lib/types'
import { fmt } from '../lib/format'

const FIELD_OPTIONS: { value: string; label: string }[] = [
  { value: 'risk_score',               label: 'Risk Score' },
  { value: 'total_paid',               label: 'Total Paid ($)' },
  { value: 'total_claims',             label: 'Total Claims' },
  { value: 'total_beneficiaries',      label: 'Total Beneficiaries' },
  { value: 'revenue_per_beneficiary',  label: 'Revenue / Beneficiary' },
  { value: 'claims_per_beneficiary',   label: 'Claims / Beneficiary' },
  { value: 'active_months',            label: 'Active Months' },
  { value: 'distinct_hcpcs',           label: 'Distinct HCPCS' },
  { value: 'flag_count',               label: 'Flag Count' },
]

const OPERATOR_OPTIONS: { value: string; label: string }[] = [
  { value: 'gt',  label: '>' },
  { value: 'gte', label: '>=' },
  { value: 'lt',  label: '<' },
  { value: 'lte', label: '<=' },
  { value: 'eq',  label: '=' },
]

const OPERATOR_LABELS: Record<string, string> = {
  gt: '>', gte: '>=', lt: '<', lte: '<=', eq: '=',
}

function RiskBadge({ score }: { score: number }) {
  const color =
    score >= 75 ? 'bg-red-900 text-red-300' :
    score >= 50 ? 'bg-orange-900 text-orange-300' :
    'bg-yellow-900 text-yellow-300'
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${color}`}>
      {score.toFixed(1)}
    </span>
  )
}

// ── New Rule Form ────────────────────────────────────────────────────────────

function NewRuleForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('')
  const [conditions, setConditions] = useState<AlertCondition[]>([
    { field: 'risk_score', operator: 'gte', value: 50 },
  ])
  const [submitting, setSubmitting] = useState(false)

  const addCondition = () => {
    setConditions([...conditions, { field: 'total_paid', operator: 'gt', value: 0 }])
  }

  const removeCondition = (idx: number) => {
    setConditions(conditions.filter((_, i) => i !== idx))
  }

  const updateCondition = (idx: number, key: keyof AlertCondition, val: string | number) => {
    const updated = [...conditions]
    if (key === 'value') {
      updated[idx] = { ...updated[idx], [key]: Number(val) }
    } else {
      updated[idx] = { ...updated[idx], [key]: val }
    }
    setConditions(updated)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || conditions.length === 0) return
    setSubmitting(true)
    try {
      await api.createAlertRule({ name: name.trim(), conditions })
      setName('')
      setConditions([{ field: 'risk_score', operator: 'gte', value: 50 }])
      onCreated()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Create New Rule</h3>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Rule Name</label>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g., High-spend providers"
          className="w-full bg-gray-800 text-gray-200 text-sm rounded px-3 py-2 border border-gray-700 focus:border-blue-600 focus:outline-none"
          required
        />
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-2">Conditions (all must match)</label>
        <div className="space-y-2">
          {conditions.map((cond, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <select
                value={cond.field}
                onChange={e => updateCondition(idx, 'field', e.target.value)}
                className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1.5 border border-gray-700 focus:border-blue-600 focus:outline-none"
              >
                {FIELD_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <select
                value={cond.operator}
                onChange={e => updateCondition(idx, 'operator', e.target.value)}
                className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1.5 border border-gray-700 focus:border-blue-600 focus:outline-none w-16"
              >
                {OPERATOR_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <input
                type="number"
                step="any"
                value={cond.value}
                onChange={e => updateCondition(idx, 'value', e.target.value)}
                className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1.5 border border-gray-700 focus:border-blue-600 focus:outline-none w-32"
              />
              {conditions.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeCondition(idx)}
                  className="text-gray-600 hover:text-red-400 transition-colors text-lg leading-none px-1"
                  title="Remove condition"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addCondition}
          className="mt-2 text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          + Add condition
        </button>
      </div>

      <button
        type="submit"
        disabled={submitting || !name.trim() || conditions.length === 0}
        className="btn-primary text-sm disabled:opacity-40"
      >
        {submitting ? 'Creating...' : 'Create Rule'}
      </button>
    </form>
  )
}

// ── Rule Row ─────────────────────────────────────────────────────────────────

function RuleRow({
  rule,
  onToggle,
  onDelete,
}: {
  rule: AlertRule
  onToggle: () => void
  onDelete: () => void
}) {
  return (
    <div className={`card p-3 flex items-center gap-4 ${!rule.enabled ? 'opacity-50' : ''}`}>
      <button
        onClick={onToggle}
        className={`w-10 h-5 rounded-full relative transition-colors ${
          rule.enabled ? 'bg-blue-600' : 'bg-gray-700'
        }`}
        title={rule.enabled ? 'Disable rule' : 'Enable rule'}
      >
        <span
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
            rule.enabled ? 'left-5' : 'left-0.5'
          }`}
        />
      </button>

      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-gray-200 truncate">{rule.name}</div>
        <div className="text-xs text-gray-500 mt-0.5 flex flex-wrap gap-1.5">
          {rule.conditions.map((c, i) => (
            <span key={i} className="bg-gray-800 px-1.5 py-0.5 rounded border border-gray-700">
              {FIELD_OPTIONS.find(f => f.value === c.field)?.label || c.field}{' '}
              {OPERATOR_LABELS[c.operator] || c.operator}{' '}
              {c.value.toLocaleString()}
            </span>
          ))}
        </div>
      </div>

      <div className="text-xs text-gray-600">
        {new Date(rule.created_at * 1000).toLocaleDateString()}
      </div>

      <button
        onClick={onDelete}
        className="text-gray-600 hover:text-red-400 transition-colors text-sm px-2"
        title="Delete rule"
      >
        Delete
      </button>
    </div>
  )
}

// ── Results Section ──────────────────────────────────────────────────────────

function ResultsSection({ results }: { results: AlertRuleResult[] }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  if (results.length === 0) {
    return (
      <div className="card p-4 text-center text-gray-500 text-sm">
        No evaluation results yet. Click "Run Rules" to evaluate.
      </div>
    )
  }

  const toggle = (id: string) => {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    <div className="space-y-2">
      {results.map(r => (
        <div key={r.rule.id} className="card">
          <button
            onClick={() => toggle(r.rule.id)}
            className="w-full p-3 flex items-center gap-3 text-left hover:bg-gray-800/50 transition-colors"
          >
            <svg
              className={`w-3.5 h-3.5 text-gray-500 transition-transform ${expanded[r.rule.id] ? 'rotate-90' : ''}`}
              fill="currentColor" viewBox="0 0 20 20"
            >
              <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
            </svg>
            <span className="text-sm font-medium text-gray-200 flex-1">{r.rule.name}</span>
            <span className={`text-xs font-mono px-2 py-0.5 rounded ${
              r.match_count > 0 ? 'bg-red-900/50 text-red-300' : 'bg-gray-800 text-gray-500'
            }`}>
              {r.match_count} match{r.match_count !== 1 ? 'es' : ''}
            </span>
          </button>

          {expanded[r.rule.id] && r.matching_providers.length > 0 && (
            <div className="border-t border-gray-800 max-h-64 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="text-gray-500 uppercase tracking-wider">
                  <tr>
                    <th className="text-left px-3 py-2">NPI</th>
                    <th className="text-left px-3 py-2">Provider</th>
                    <th className="text-left px-3 py-2">State</th>
                    <th className="text-right px-3 py-2">Risk</th>
                    <th className="text-right px-3 py-2">Total Paid</th>
                    <th className="text-right px-3 py-2">Flags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {r.matching_providers.map(p => (
                    <tr key={p.npi} className="hover:bg-gray-800/40">
                      <td className="px-3 py-1.5">
                        <Link to={`/providers/${p.npi}`} className="text-blue-400 hover:underline font-mono">
                          {p.npi}
                        </Link>
                      </td>
                      <td className="px-3 py-1.5 text-gray-300 truncate max-w-[200px]">{p.provider_name || '--'}</td>
                      <td className="px-3 py-1.5 text-gray-400">{p.state || '--'}</td>
                      <td className="px-3 py-1.5 text-right"><RiskBadge score={p.risk_score} /></td>
                      <td className="px-3 py-1.5 text-right text-gray-300 font-mono">{fmt(p.total_paid)}</td>
                      <td className="px-3 py-1.5 text-right text-gray-400">{p.flag_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {expanded[r.rule.id] && r.matching_providers.length === 0 && (
            <div className="border-t border-gray-800 px-3 py-3 text-xs text-gray-600">
              No providers matched this rule.
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function AlertRules() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)

  const { data: rulesData, isLoading } = useQuery({
    queryKey: ['alertRules'],
    queryFn: api.alertRules,
  })

  const { data: resultsData } = useQuery({
    queryKey: ['alertResults'],
    queryFn: api.alertResults,
  })

  const toggleMut = useMutation({
    mutationFn: (rule: AlertRule) =>
      api.updateAlertRule(rule.id, { enabled: !rule.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alertRules'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteAlertRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alertRules'] }),
  })

  const evaluateMut = useMutation({
    mutationFn: () => api.evaluateAlerts(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alertResults'] }),
  })

  const rules = rulesData?.rules ?? []
  const results = resultsData?.results ?? []

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Alert Rules</h1>
          <p className="text-sm text-gray-500 mt-1">
            Define custom rules to flag providers matching specific criteria.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowForm(!showForm)}
            className={showForm ? 'btn-ghost' : 'btn-primary'}
          >
            {showForm ? 'Cancel' : 'New Rule'}
          </button>
          <button
            onClick={() => evaluateMut.mutate()}
            disabled={evaluateMut.isPending || rules.length === 0}
            className="btn-primary disabled:opacity-40"
          >
            {evaluateMut.isPending ? 'Running...' : 'Run Rules'}
          </button>
        </div>
      </div>

      {/* New Rule Form */}
      {showForm && (
        <NewRuleForm
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['alertRules'] })
            setShowForm(false)
          }}
        />
      )}

      {/* Rules List */}
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Rules ({rules.length})
        </h2>
        {isLoading ? (
          <div className="card p-4 text-center text-gray-500 text-sm">Loading rules...</div>
        ) : rules.length === 0 ? (
          <div className="card p-4 text-center text-gray-500 text-sm">
            No rules defined. Create one to get started.
          </div>
        ) : (
          <div className="space-y-2">
            {rules.map(rule => (
              <RuleRow
                key={rule.id}
                rule={rule}
                onToggle={() => toggleMut.mutate(rule)}
                onDelete={() => deleteMut.mutate(rule.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Evaluation Results
        </h2>
        <ResultsSection results={results} />
      </div>
    </div>
  )
}
