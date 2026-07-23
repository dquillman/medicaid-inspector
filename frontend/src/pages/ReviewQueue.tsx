import { useState, useRef, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ReviewItem, AuditEntry, CaseNote } from '../lib/types'
import { fmt } from '../lib/format'
import { threatColor, magnitudeGlyph } from '../lib/threat'
import { STATUS_LABELS, STATUS_COLORS } from '../lib/reviewStatus'
import { CASE_STAGES } from '../lib/queueStatus'
import { ArrowDownTrayIcon } from '../components/icons'
import EmptyState from '../components/EmptyState'
import QuickTriagePanel from '../components/QuickTriagePanel'
import ProviderFlags from '../components/ProviderFlags'
import RecencyBadge from '../components/RecencyBadge'
import { useProviderFlags } from '../hooks/useProviderFlags'

// The queue speaks ONE status model: the case-ledger pipeline (see queueStatus).
// Filter keys are the 5 stage values plus 'all'.
type StatusFilter = 'all' | 'open' | 'under_review' | 'confirmed' | 'referred' | 'dismissed' | 'archived'

// The Fraud Brain is the queue's authority, so its fused meta-score is the
// primary number. The raw 18-signal risk (one of the Brain's five inputs) is
// kept as a small secondary line so the analyst can still see it.
function BrainCell({ npi, risk }: { npi: string; risk: number }) {
  const { brainRank, brainScore } = useProviderFlags()
  const rank = brainRank(npi)
  const bscore = brainScore(npi)
  return (
    <div className="flex flex-col gap-0.5 leading-none">
      {bscore != null ? (
        <span
          className="inline-flex items-center gap-1 font-mono tabular-nums text-sm font-bold"
          style={{ color: threatColor(bscore) }}
          title={`Brain score ${bscore.toFixed(1)}/100${rank ? ` — Brain #${rank}` : ''} (fused across all sources)`}
        >
          <span aria-hidden="true">{magnitudeGlyph(bscore)}</span>{bscore.toFixed(1)}
        </span>
      ) : (
        <span className="text-gray-600 text-xs" title="Not on the current Brain board">--</span>
      )}
      <span
        className="font-mono tabular-nums text-[10px] text-gray-500"
        title={`Raw rule-signal risk ${risk.toFixed(1)}/100`}
      >
        risk {risk.toFixed(1)}
      </span>
    </div>
  )
}

function NotesCell({ item, onSave }: { item: ReviewItem; onSave: (notes: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.notes)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { setValue(item.notes) }, [item.notes])

  const handleClick = () => {
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const handleBlur = () => {
    setEditing(false)
    if (value !== item.notes) onSave(value)
  }

  if (editing) {
    return (
      <textarea
        ref={inputRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={handleBlur}
        className="w-full bg-gray-800 text-gray-200 text-xs rounded px-2 py-1 border border-blue-600 focus:outline-none resize-none"
        rows={2}
      />
    )
  }

  return (
    <button
      onClick={handleClick}
      className="text-left text-xs text-gray-500 hover:text-gray-300 transition-colors truncate max-w-[180px] block"
      title={item.notes || 'Click to add notes'}
    >
      {item.notes || <span className="italic">Add notes…</span>}
    </button>
  )
}

function AssignedToCell({ item, onSave }: { item: ReviewItem; onSave: (assignedTo: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.assigned_to ?? '')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { setValue(item.assigned_to ?? '') }, [item.assigned_to])

  const handleClick = () => {
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const handleBlur = () => {
    setEditing(false)
    if (value !== (item.assigned_to ?? '')) onSave(value)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); inputRef.current?.blur() }
    if (e.key === 'Escape') { setValue(item.assigned_to ?? ''); setEditing(false) }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        placeholder="Name..."
        className="w-full bg-gray-800 text-gray-200 text-xs rounded px-2 py-1 border border-cyan-600 focus:outline-none"
      />
    )
  }

  return (
    <button
      onClick={handleClick}
      className="text-left text-xs text-gray-500 hover:text-gray-300 transition-colors truncate max-w-[120px] block"
      title={item.assigned_to || 'Click to assign'}
    >
      {item.assigned_to || <span className="italic">Assign...</span>}
    </button>
  )
}

function formatTimestamp(ts: number) {
  if (!ts) return '--'
  const d = new Date(ts * 1000)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

function AuditTrailPanel({ npi }: { npi: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['review-history', npi],
    queryFn: () => api.getReviewHistory(npi),
  })

  if (isLoading) return <div className="text-xs text-gray-500 py-2 px-4">Loading history...</div>

  const trail: AuditEntry[] = data?.audit_trail ?? []
  if (trail.length === 0) return <div className="text-xs text-gray-600 py-2 px-4 italic">No history yet</div>

  return (
    <div className="px-4 py-2 max-h-48 overflow-y-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-600 border-b border-gray-800">
            <th className="text-left py-1 pr-3">Time</th>
            <th className="text-left py-1 pr-3">Action</th>
            <th className="text-left py-1 pr-3">From</th>
            <th className="text-left py-1 pr-3">To</th>
            <th className="text-left py-1">Note</th>
          </tr>
        </thead>
        <tbody>
          {trail.slice().reverse().map((entry, i) => (
            // Audit-trail entries don't carry a server-assigned id, so build
            // a stable composite key from timestamp + action + prev/new status.
            // Falling back to index only when all identifying fields are blank.
            <tr
              key={`${entry.timestamp ?? ''}-${entry.action ?? ''}-${entry.previous_status ?? ''}-${entry.new_status ?? ''}-${i}`}
              className="border-b border-gray-800/50"
            >
              <td className="py-1 pr-3 text-gray-500 whitespace-nowrap">{formatTimestamp(entry.timestamp)}</td>
              <td className="py-1 pr-3 text-gray-400">{({
                status_change: 'Status',
                assignment_change: 'Assignment',
                queue_status_change: 'Case',
                case_note_added: 'Note',
                case_note_redacted: 'Redaction',
              } as Record<string, string>)[entry.action] ?? entry.action}</td>
              <td className="py-1 pr-3">
                <span className={`px-1.5 py-0.5 rounded ${STATUS_COLORS[entry.previous_status] ?? 'text-gray-500'}`}>
                  {STATUS_LABELS[entry.previous_status] ?? entry.previous_status}
                </span>
              </td>
              <td className="py-1 pr-3">
                <span className={`px-1.5 py-0.5 rounded ${STATUS_COLORS[entry.new_status] ?? 'text-gray-500'}`}>
                  {STATUS_LABELS[entry.new_status] ?? entry.new_status}
                </span>
              </td>
              <td className="py-1 text-gray-500 max-w-[200px] truncate" title={entry.note}>{entry.note || '--'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Append-only case-note log — the on-the-record counterpart to the editable
// summary box (NotesCell). Entries are permanent and authored (human vs HAL);
// the only mutation is an admin redact, which leaves a tombstone.
function CaseNotesPanel({ npi }: { npi: string }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['case-notes', npi],
    queryFn: () => api.getCaseNotes(npi),
  })

  const addMutation = useMutation({
    mutationFn: (text: string) => api.addCaseNote(npi, text),
    onSuccess: () => {
      setDraft('')
      setError('')
      queryClient.invalidateQueries({ queryKey: ['case-notes', npi] })
      queryClient.invalidateQueries({ queryKey: ['review-history', npi] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const redactMutation = useMutation({
    mutationFn: (noteId: string) => api.redactCaseNote(npi, noteId),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['case-notes', npi] })
      queryClient.invalidateQueries({ queryKey: ['review-history', npi] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const submit = () => {
    const text = draft.trim()
    if (text && !addMutation.isPending) addMutation.mutate(text)
  }

  const notes: CaseNote[] = data?.case_notes ?? []

  return (
    <div className="px-4 py-3 border-b border-gray-800">
      <p className="text-[10px] uppercase tracking-widest text-gray-600 font-bold mb-2">
        Case notes <span className="normal-case font-normal tracking-normal">— append-only, on the record</span>
      </p>
      {isLoading ? (
        <div className="text-xs text-gray-500 py-1">Loading notes...</div>
      ) : notes.length === 0 ? (
        <div className="text-xs text-gray-600 italic py-1">No case notes yet — the first entry starts the record.</div>
      ) : (
        <ul className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
          {notes.map(n => (
            <li key={n.id} className="flex items-start gap-2 text-xs group">
              <span className="text-gray-600 whitespace-nowrap pt-px">{formatTimestamp(n.created_at)}</span>
              <span
                className={`px-1 rounded text-[10px] font-bold uppercase pt-px ${
                  n.actor_type === 'ai' ? 'bg-purple-950 text-purple-400' : 'bg-cyan-950 text-cyan-400'
                }`}
                title={`Authored by ${n.actor} (${n.actor_type})`}
              >
                {n.actor_type === 'ai' ? 'HAL' : n.actor}
              </span>
              {n.redacted ? (
                <span className="text-gray-600 italic" title={`Redacted by ${n.redacted_by}`}>
                  [redacted by {n.redacted_by}]
                </span>
              ) : (
                <>
                  <span className="text-gray-300 whitespace-pre-wrap break-words flex-1">{n.text}</span>
                  <button
                    onClick={() => {
                      if (window.confirm('Redact this note? The text is blanked but a tombstone stays in the log. Admin only.')) {
                        redactMutation.mutate(n.id)
                      }
                    }}
                    title="Admin only: blank this note, leaving a tombstone"
                    className="opacity-0 group-hover:opacity-100 text-[10px] text-gray-600 hover:text-red-400 transition-opacity shrink-0"
                  >
                    redact
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2 mt-2">
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit() } }}
          placeholder="Add a note to the record… (permanent)"
          maxLength={4000}
          className="flex-1 bg-gray-800 text-gray-200 text-xs rounded px-2 py-1.5 border border-gray-700 focus:outline-none focus:border-cyan-600 placeholder:text-gray-600"
        />
        <button
          onClick={submit}
          disabled={!draft.trim() || addMutation.isPending}
          className="px-3 py-1.5 text-xs rounded bg-cyan-900 hover:bg-cyan-800 text-cyan-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {addMutation.isPending ? 'Adding…' : 'Append'}
        </button>
      </div>
      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  )
}

// The case-ledger status — now the queue's ONE status control (the legacy
// workflow dropdown was retired). Human-gated and audited: setting it is an
// explicit human action, so tip_filed / confirmed are permitted here. The
// Fraud Brain reads this value one-way for badges; it never affects the score.
function QueueStatusDropdown({ item, onChange }: { item: ReviewItem; onChange: (status: string) => void }) {
  return (
    <select
      // Legacy 'tip_filed' has no stage of its own (it now means "Reported" =
      // 'referred'), so show it as 'referred' in the picker.
      value={item.queue_status === 'tip_filed' ? 'referred' : (item.queue_status ?? 'open')}
      onChange={e => onChange(e.target.value)}
      title="Case status (audited). The Fraud Brain reads this read-only."
      className="bg-gray-800 text-xs rounded px-1.5 py-1 border border-gray-700 text-cyan-300 focus:outline-none focus:border-cyan-500 cursor-pointer"
    >
      {CASE_STAGES.map(s => (
        <option key={s.value} value={s.value} title={s.blurb}>{s.label}</option>
      ))}
    </select>
  )
}

function ReviewRow({
  item,
  selected,
  expanded,
  triageOpen,
  rowIndex,
  onToggleSelect,
  onToggleExpand,
  onToggleTriage,
  onQueueStatusChange,
  onNotesSave,
  onAssignedToSave,
}: {
  item: ReviewItem
  selected: boolean
  expanded: boolean
  triageOpen: boolean
  rowIndex: number
  onToggleSelect: (npi: string) => void
  onToggleExpand: (npi: string) => void
  onToggleTriage: (npi: string) => void
  onQueueStatusChange: (npi: string, status: string) => void
  onNotesSave: (npi: string, notes: string) => void
  onAssignedToSave: (npi: string, assignedTo: string) => void
}) {
  const isFraud = item.queue_status === 'confirmed'
  return (
    <>
      <tr
        className={`border-b border-gray-800 hover:bg-gray-800/40 transition-colors ${
          selected ? 'bg-blue-900/20' : isFraud ? 'bg-red-950/20' : rowIndex % 2 === 1 ? 'bg-gray-900/30' : ''
        } ${isFraud ? 'row-fraud' : ''}`}
        style={isFraud ? undefined : { borderLeft: `3px solid ${threatColor(item.risk_score)}` }}
      >
        <td className="px-3 py-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(item.npi)}
            className="accent-blue-500 cursor-pointer"
          />
        </td>
        <td className="px-4 py-3">
          <Link
            to={`/providers/${item.npi}`}
            className="text-blue-400 hover:text-blue-300 font-mono-data text-sm underline underline-offset-2"
          >
            {item.npi}
          </Link>
        </td>
        <td className="px-4 py-3 text-sm text-gray-300 max-w-[220px]" title={item.provider_name}>
          {/* Only the name truncates (min-w-0 lets it shrink inside the flex
              row); badges have shrink-0 so they always render in FULL — never
              clipped mid-badge by the name's overflow-hidden ellipsis. */}
          <div className="flex items-center min-w-0">
            <span className="truncate min-w-0">
              {item.provider_name || <span className="text-gray-600 italic">--</span>}
            </span>
            <ProviderFlags npi={item.npi} className="ml-1.5 shrink-0" />
            {item.stale && (
              <span
                className="ml-1.5 shrink-0 align-middle text-[10px] font-mono font-semibold leading-none px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/40"
                title={`No case activity for ${item.stale_days ?? '14+'} days — needs a nudge`}
              >
                IDLE {item.stale_days != null ? `${item.stale_days}d` : ''}
              </span>
            )}
            {/* DATA recency (distinct from CASE staleness above): is the scheme
                still active, or is this a recovery lead? */}
            <span className="ml-1.5 shrink-0">
              <RecencyBadge recency={item.recency} lastActiveMonth={item.last_active_month} dataAgeMonths={item.data_age_months} />
            </span>
          </div>
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{item.state || '--'}</td>
        <td className="px-4 py-3">
          <BrainCell npi={item.npi} risk={item.risk_score} />
        </td>
        <td className="px-4 py-3 text-sm text-gray-300">
          {item.flags.length > 0 ? (
            <span className="text-red-400 font-medium">{item.flags.length} flag{item.flags.length !== 1 ? 's' : ''}</span>
          ) : (
            <span className="text-gray-600">--</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-gray-400">{fmt(item.total_paid)}</td>
        <td className="px-4 py-3">
          <QueueStatusDropdown item={item} onChange={status => onQueueStatusChange(item.npi, status)} />
        </td>
        <td className="px-4 py-3">
          <AssignedToCell item={item} onSave={assignedTo => onAssignedToSave(item.npi, assignedTo)} />
        </td>
        <td className="px-4 py-3">
          <NotesCell item={item} onSave={notes => onNotesSave(item.npi, notes)} />
        </td>
        <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
          {formatTimestamp(item.updated_at)}
        </td>
        <td className="px-4 py-3">
          <div className="flex gap-1">
            <button
              onClick={() => onToggleTriage(item.npi)}
              title="Quick triage memo"
              className={`px-2 py-1 text-xs rounded transition-colors ${
                triageOpen
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200'
              }`}
            >
              {triageOpen ? 'Close' : 'Triage'}
            </button>
            <button
              onClick={() => onToggleExpand(item.npi)}
              title="View audit history"
              className={`px-2 py-1 text-xs rounded transition-colors ${
                expanded
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200'
              }`}
            >
              {expanded ? 'Hide' : 'History'}
            </button>
          </div>
        </td>
      </tr>
      {triageOpen && (
        <QuickTriagePanel item={item} onClose={() => onToggleTriage(item.npi)} />
      )}
      {expanded && (
        <tr className="bg-gray-900/50">
          <td colSpan={12} className="p-0">
            <CaseNotesPanel npi={item.npi} />
            <AuditTrailPanel npi={item.npi} />
          </td>
        </tr>
      )}
    </>
  )
}

function StatusTab({
  label,
  count,
  active,
  onClick,
  variant = 'default',
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
  variant?: 'default' | 'danger'
}) {
  const isDanger = variant === 'danger'
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded transition-colors flex items-center gap-2 ${
        active
          ? isDanger
            ? 'bg-red-700 text-white border border-red-500'
            : 'bg-blue-600 text-white'
          : isDanger
            ? 'bg-red-950 text-red-400 border border-red-800 hover:bg-red-900 hover:text-red-300'
            : 'bg-gray-800 text-gray-400 hover:text-gray-200 hover:bg-gray-700'
      }`}
    >
      {isDanger && '\u26A0 '}{label}
      <span className={`text-xs px-1.5 py-0.5 rounded-full font-bold ${
        active
          ? isDanger ? 'bg-red-500' : 'bg-blue-500'
          : isDanger ? 'bg-red-800' : 'bg-gray-700'
      }`}>
        {count}
      </span>
    </button>
  )
}

type SortField = 'npi' | 'provider_name' | 'state' | 'brain' | 'risk_score' | 'flags' | 'total_paid' | 'status' | 'updated_at'
type SortDir = 'asc' | 'desc'

function SortHeader({ label, field, sortField, sortDir, onSort }: {
  label: string
  field: SortField
  sortField: SortField
  sortDir: SortDir
  onSort: (f: SortField) => void
}) {
  const active = sortField === field
  return (
    <th
      className="px-4 py-3 cursor-pointer hover:text-gray-300 select-none transition-colors"
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          <span className="text-blue-400">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>
        ) : (
          <span className="text-gray-700">\u25BC</span>
        )}
      </span>
    </th>
  )
}

export default function ReviewQueue() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const statusParam = searchParams.get('status') as StatusFilter | null
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(statusParam ?? 'all')
  const [selectedNpis, setSelectedNpis] = useState<Set<string>>(new Set())
  const [npiSearch, setNpiSearch] = useState('')
  // The Fraud Brain is the boss: default the queue to Brain rank ascending
  // (#1 at the top) so the board's own ordering is what analysts see.
  const [sortField, setSortField] = useState<SortField>('brain')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const { brainRank } = useProviderFlags()

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir(field === 'risk_score' || field === 'total_paid' || field === 'flags' || field === 'updated_at' ? 'desc' : 'asc')
    }
  }

  // The visible queue is a small set (Brain top-N + human-actioned cases), so
  // fetch it whole and filter/count by case-ledger status CLIENT-SIDE — no
  // server-side status param, one status model, no separate counts endpoint.
  const { data, isLoading } = useQuery({
    queryKey: ['review-queue'],
    queryFn: () => api.reviewQueue({ page: 1, limit: 500 }),
    refetchInterval: 15000,
  })

  // Clear selection when the filter changes
  useEffect(() => { setSelectedNpis(new Set()) }, [statusFilter])

  const [expandedNpis, setExpandedNpis] = useState<Set<string>>(new Set())
  const [triageNpis, setTriageNpis] = useState<Set<string>>(new Set())

  const updateMutation = useMutation({
    mutationFn: ({ npi, update }: { npi: string; update: { notes?: string; assigned_to?: string | null } }) =>
      api.updateReview(npi, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-history'] })
    },
  })

  // Bulk case-ledger change — no bulk endpoint exists, so apply setQueueStatus
  // per NPI (the visible set is small). tip_filed/confirmed are human-gated at
  // the API, and the analyst is signed in, so those transitions are permitted.
  const bulkMutation = useMutation({
    mutationFn: async ({ npis, newStatus }: { npis: string[]; newStatus: string }) => {
      for (const npi of npis) await api.setQueueStatus(npi, newStatus)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-history'] })
      setSelectedNpis(new Set())
    },
  })

  const queueStatusMutation = useMutation({
    mutationFn: ({ npi, newStatus }: { npi: string; newStatus: string }) =>
      api.setQueueStatus(npi, newStatus),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
      queryClient.invalidateQueries({ queryKey: ['review-history'] })
    },
  })

  const handleQueueStatusChange = (npi: string, newStatus: string) =>
    queueStatusMutation.mutate({ npi, newStatus })

  const handleNotesSave = (npi: string, notes: string) =>
    updateMutation.mutate({ npi, update: { notes } })

  const handleAssignedToSave = (npi: string, assignedTo: string) =>
    updateMutation.mutate({ npi, update: { assigned_to: assignedTo || null } })

  const handleToggleExpand = (npi: string) => {
    setExpandedNpis(prev => {
      const next = new Set(prev)
      next.has(npi) ? next.delete(npi) : next.add(npi)
      return next
    })
  }

  const handleToggleTriage = (npi: string) => {
    setTriageNpis(prev => {
      const next = new Set(prev)
      next.has(npi) ? next.delete(npi) : next.add(npi)
      return next
    })
  }

  const handleToggleSelect = (npi: string) => {
    setSelectedNpis(prev => {
      const next = new Set(prev)
      next.has(npi) ? next.delete(npi) : next.add(npi)
      return next
    })
  }

  const handleSelectAll = () => {
    const allNpis = items.map(i => i.npi)
    const allSelected = allNpis.every(n => selectedNpis.has(n))
    if (allSelected) {
      setSelectedNpis(new Set())
    } else {
      setSelectedNpis(new Set(allNpis))
    }
  }

  const handleBulkAction = (newStatus: string) => {
    const npis = Array.from(selectedNpis)
    if (npis.length === 0) return
    bulkMutation.mutate({ npis, newStatus })
  }

  const handleExportCSV = () => {
    const confirmed = items.filter(i => i.queue_status === 'confirmed')
    if (confirmed.length === 0) {
      alert('No confirmed cases to export. Set a case to "Confirmed" first.')
      return
    }
    const headers = ['NPI', 'Name', 'State', 'Risk Score', 'Flags', 'Total Paid', 'Total Claims', 'Status', 'Notes']
    const rows = confirmed.map(i => [
      i.npi,
      `"${(i.provider_name ?? '').replace(/"/g, '""')}"`,
      i.state ?? '',
      i.risk_score.toFixed(1),
      i.flags.length.toString(),
      i.total_paid.toString(),
      i.total_claims.toString(),
      i.queue_status ?? 'open',
      `"${(i.notes ?? '').replace(/"/g, '""')}"`,
    ])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `confirmed_cases_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const rawItems   = data?.items ?? []

  // Case-ledger counts, computed client-side over the whole visible queue.
  // 'referred' (Reported) folds in the legacy 'tip_filed' value.
  const qs = (i: ReviewItem) => i.queue_status ?? 'open'
  const isReported = (i: ReviewItem) => qs(i) === 'referred' || qs(i) === 'tip_filed'
  const queueCounts = {
    total:        rawItems.length,
    open:         rawItems.filter(i => qs(i) === 'open').length,
    under_review: rawItems.filter(i => qs(i) === 'under_review').length,
    confirmed:    rawItems.filter(i => qs(i) === 'confirmed').length,
    referred:     rawItems.filter(isReported).length,
    dismissed:    rawItems.filter(i => qs(i) === 'dismissed').length,
    archived:     rawItems.filter(i => qs(i) === 'archived').length,
  }

  // Filter by the selected stage (client-side), then NPI search.
  const statusFiltered =
    statusFilter === 'all'      ? rawItems
    : statusFilter === 'referred' ? rawItems.filter(isReported)
    : rawItems.filter(i => qs(i) === statusFilter)
  const searchFiltered = npiSearch.trim()
    ? statusFiltered.filter(i => i.npi.includes(npiSearch.trim()))
    : statusFiltered

  // Client-side sort
  const sortedItems = [...searchFiltered].sort((a, b) => {
    let cmp = 0
    switch (sortField) {
      case 'npi':           cmp = a.npi.localeCompare(b.npi); break
      case 'provider_name': cmp = (a.provider_name || '').localeCompare(b.provider_name || ''); break
      case 'state':         cmp = (a.state || '').localeCompare(b.state || ''); break
      // Brain rank asc = board order (#1 first). Off-board cases (human-actioned
      // but no longer on the top-N) have no rank → sort last, ties broken by risk.
      case 'brain': {
        const ra = brainRank(a.npi) ?? Number.POSITIVE_INFINITY
        const rb = brainRank(b.npi) ?? Number.POSITIVE_INFINITY
        cmp = ra !== rb ? ra - rb : b.risk_score - a.risk_score
        break
      }
      case 'risk_score':    cmp = a.risk_score - b.risk_score; break
      case 'flags':         cmp = a.flags.length - b.flags.length; break
      case 'total_paid':    cmp = a.total_paid - b.total_paid; break
      case 'status':        cmp = qs(a).localeCompare(qs(b)); break
      case 'updated_at':    cmp = (a.updated_at || 0) - (b.updated_at || 0); break
    }
    return sortDir === 'asc' ? cmp : -cmp
  })

  const items      = sortedItems
  const total      = searchFiltered.length
  const allOnPageSelected = items.length > 0 && items.every(i => selectedNpis.has(i.npi))

  // Tabs follow the pipeline order: New → Investigating → Confirmed → Reported,
  // with Dismissed (off-ramp) last.
  const tabs: { key: StatusFilter; label: string; count: number }[] = [
    { key: 'all',          label: 'All',           count: queueCounts.total },
    { key: 'open',         label: 'New',           count: queueCounts.open },
    { key: 'under_review', label: 'Investigating', count: queueCounts.under_review },
    { key: 'confirmed',    label: 'Confirmed',     count: queueCounts.confirmed },
    { key: 'referred',     label: 'Reported',      count: queueCounts.referred },
    { key: 'dismissed',    label: 'Dismissed',     count: queueCounts.dismissed },
    { key: 'archived',     label: 'Archived',      count: queueCounts.archived },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white uppercase tracking-wide">Investigation Queue</h1>
          <p className="text-gray-500 text-xs mt-1 uppercase tracking-wider">
            Flagged Providers Requiring Human Review
          </p>
          <p className="text-xs text-gray-400 mt-2">
            <span className="text-slate-300 font-semibold">{queueCounts.open}</span> new
            <span className="text-gray-600 mx-2">&middot;</span>
            <span className="text-red-400 font-semibold">{queueCounts.confirmed}</span> confirmed fraud
            <span className="text-gray-600 mx-2">&middot;</span>
            <span className="text-emerald-400 font-semibold">{queueCounts.referred}</span> reported to authorities
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <input
              type="text"
              value={npiSearch}
              onChange={e => setNpiSearch(e.target.value)}
              placeholder="Search NPI..."
              className="input w-44 pl-8 text-sm font-mono"
            />
            <svg className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {npiSearch && (
              <button
                onClick={() => setNpiSearch('')}
                className="absolute right-2 top-2 text-gray-500 hover:text-gray-300 text-sm"
              >
                x
              </button>
            )}
          </div>
          <button
            onClick={() => window.open('/api/review/export/csv', '_blank', 'noopener,noreferrer')}
            className="px-4 py-2 text-sm rounded transition-colors border font-medium flex items-center gap-2 bg-gray-700 hover:bg-gray-600 text-gray-200 border-gray-600"
            aria-label="Export full review queue as CSV"
          >
            Export All CSV
          </button>
          <button
            onClick={handleExportCSV}
            className={`px-4 py-2 text-sm rounded transition-colors border font-medium flex items-center gap-2 ${
              statusFilter === 'confirmed'
                ? 'bg-red-700 hover:bg-red-600 text-white border-red-500 shadow-lg shadow-red-900/30'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-200 border-gray-600'
            }`}
            aria-label="Export confirmed cases as CSV"
          >
            {statusFilter === 'confirmed' && <ArrowDownTrayIcon />}
            Export Confirmed CSV
          </button>
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex gap-2 flex-wrap">
        {tabs.map(tab => (
          <StatusTab
            key={tab.key}
            label={tab.label}
            count={tab.count}
            active={statusFilter === tab.key}
            onClick={() => setStatusFilter(tab.key)}
            variant={tab.key === 'confirmed' ? 'danger' : 'default'}
          />
        ))}
      </div>

      {/* Bulk action bar */}
      {selectedNpis.size > 0 && (
        <div className="flex items-center gap-4 px-5 py-3 bg-blue-950/60 border-2 border-blue-600 rounded-lg shadow-lg">
          <span className="text-sm text-blue-200 font-bold uppercase tracking-wider">
            {selectedNpis.size} Selected
          </span>
          <div className="flex gap-2 ml-2">
            <button
              onClick={() => handleBulkAction('under_review')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white font-medium transition-colors disabled:opacity-50"
            >
              Investigating
            </button>
            <button
              onClick={() => handleBulkAction('confirmed')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-red-700 hover:bg-red-600 text-white font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
            >
              Confirm Fraud
            </button>
            <button
              onClick={() => handleBulkAction('referred')}
              disabled={bulkMutation.isPending}
              className="px-4 py-1.5 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
            >
              Mark Reported
            </button>
            <button
              onClick={() => handleBulkAction('dismissed')}
              disabled={bulkMutation.isPending}
              title="Judgment: NOT fraud — this trains the model"
              className="px-4 py-1.5 text-xs rounded bg-gray-600 hover:bg-gray-500 text-white font-medium transition-colors disabled:opacity-50"
            >
              Dismiss
            </button>
            <button
              onClick={() => handleBulkAction('archived')}
              disabled={bulkMutation.isPending}
              title="Close WITHOUT judgment (too old / not pursuing) — never trains the model"
              className="px-4 py-1.5 text-xs rounded bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-600 font-medium transition-colors disabled:opacity-50"
            >
              Archive
            </button>
          </div>
          <button
            onClick={() => setSelectedNpis(new Set())}
            className="ml-auto text-xs text-gray-400 hover:text-gray-200"
          >
            Clear selection
          </button>
        </div>
      )}

      {/* Table */}
      <div className="card p-0 overflow-x-auto">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500 text-sm">Loading…</div>
        ) : items.length === 0 ? (
          <EmptyState
            variant="no-results"
            title="No items in this queue"
            description="Providers flagged for review will appear here."
          />
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-500 uppercase tracking-wider">
                <th className="px-3 py-3">
                  <input
                    type="checkbox"
                    checked={allOnPageSelected}
                    onChange={handleSelectAll}
                    className="accent-blue-500 cursor-pointer"
                    title="Select all on page"
                  />
                </th>
                <SortHeader label="NPI" field="npi" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Name" field="provider_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="St" field="state" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Brain" field="brain" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Signals" field="flags" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Total Paid" field="total_paid" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Status" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3">Assigned To</th>
                <th className="px-4 py-3">Notes</th>
                <SortHeader label="Last Updated" field="updated_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => (
                <ReviewRow
                  key={item.npi}
                  item={item}
                  rowIndex={idx}
                  selected={selectedNpis.has(item.npi)}
                  expanded={expandedNpis.has(item.npi)}
                  triageOpen={triageNpis.has(item.npi)}
                  onToggleSelect={handleToggleSelect}
                  onToggleExpand={handleToggleExpand}
                  onToggleTriage={handleToggleTriage}
                  onQueueStatusChange={handleQueueStatusChange}
                  onNotesSave={handleNotesSave}
                  onAssignedToSave={handleAssignedToSave}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {items.length > 0 && (
        <div className="text-xs text-gray-500">{total.toLocaleString()} case{total === 1 ? '' : 's'} shown</div>
      )}

      {/* MFCU Referral Status Panel */}
      <ReferralStatusPanel />
    </div>
  )
}

function ReferralStatusPanel() {
  const { data: refData } = useQuery({
    queryKey: ['referral-stats'],
    queryFn: api.referralStats,
    refetchInterval: 30000,
  })
  const { data: listData } = useQuery({
    queryKey: ['referrals-list'],
    queryFn: () => api.listReferrals(),
    refetchInterval: 30000,
  })

  const stats = refData
  const referrals = listData?.referrals ?? []

  const STAGE_LABELS: Record<string, string> = {
    draft: 'Draft',
    submitted: 'Submitted',
    acknowledged: 'Acknowledged',
    under_investigation: 'Under Investigation',
    outcome_received: 'Outcome Received',
  }
  const STAGE_COLORS: Record<string, string> = {
    draft: 'text-gray-400 bg-gray-700',
    submitted: 'text-orange-400 bg-orange-900/40',
    acknowledged: 'text-blue-400 bg-blue-900/40',
    under_investigation: 'text-purple-400 bg-purple-900/40',
    outcome_received: 'text-green-400 bg-green-900/40',
  }

  if (!stats && referrals.length === 0) return null

  return (
    <div className="card p-5">
      <h2 className="text-lg font-bold text-white uppercase tracking-wide mb-4">MFCU Referral Tracker</h2>

      {stats && stats.total_referrals > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-orange-400">{stats.total_referrals}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Total Referrals</div>
          </div>
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-blue-400">{stats.unique_providers}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Unique Providers</div>
          </div>
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-purple-400">{stats.by_stage?.under_investigation ?? 0}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Under Investigation</div>
          </div>
          <div className="bg-gray-800 rounded p-3 text-center">
            <div className="text-2xl font-bold text-green-400">{stats.by_stage?.outcome_received ?? 0}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-1">Outcomes Received</div>
          </div>
        </div>
      )}

      {referrals.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-500 uppercase tracking-wider">
                <th className="px-3 py-2">Ref #</th>
                <th className="px-3 py-2">NPI</th>
                <th className="px-3 py-2">Provider</th>
                <th className="px-3 py-2">Stage</th>
                <th className="px-3 py-2">Jurisdiction</th>
                <th className="px-3 py-2">Submitted</th>
                <th className="px-3 py-2">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {referrals.slice(0, 10).map(ref => (
                <tr key={ref.id} className="border-b border-gray-800 hover:bg-gray-800/40">
                  <td className="px-3 py-2 text-xs font-mono text-orange-400">{ref.referral_id}</td>
                  <td className="px-3 py-2">
                    <Link to={`/providers/${ref.npi}`} className="text-blue-400 hover:text-blue-300 text-xs font-mono underline">
                      {ref.npi}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-gray-300 text-xs truncate max-w-[160px]">{ref.provider_name || '--'}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded ${STAGE_COLORS[ref.stage] ?? 'text-gray-400 bg-gray-700'}`}>
                      {STAGE_LABELS[ref.stage] ?? ref.stage}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500">{ref.jurisdiction || '--'}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {ref.referral_date ? new Date(ref.referral_date * 1000).toLocaleDateString() : '--'}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {ref.outcome ? (
                      <span className="text-green-400">{ref.outcome.replace('_', ' ')}</span>
                    ) : (
                      <span className="text-gray-600">Pending</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-500 text-sm">No MFCU referrals yet. Use "Refer to MFCU" on confirmed fraud cases.</p>
      )}
    </div>
  )
}
