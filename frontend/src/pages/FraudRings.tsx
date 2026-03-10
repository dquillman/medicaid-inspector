import { useState, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { FraudRingSummary, FraudRingDetail, FraudRingMember, FraudRingEdge } from '../lib/types'

function fmt(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v?.toFixed(2) ?? 0}`
}

function RiskBadge({ score }: { score: number }) {
  const cls = score >= 50
    ? 'bg-red-900 text-red-300'
    : score >= 25
      ? 'bg-orange-900 text-orange-300'
      : 'bg-gray-800 text-gray-400'
  return (
    <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${cls}`}>
      {score.toFixed(0)}
    </span>
  )
}

const CONNECTION_COLORS: Record<string, string> = {
  shared_address: '#f59e0b',
  shared_phone: '#10b981',
  shared_fax: '#8b5cf6',
  shared_billing_npi: '#3b82f6',
  shared_beneficiaries: '#ef4444',
}

const CONNECTION_LABELS: Record<string, string> = {
  shared_address: 'Address',
  shared_phone: 'Phone',
  shared_fax: 'Fax',
  shared_billing_npi: 'Billing NPI',
  shared_beneficiaries: 'Beneficiaries',
}

// ---- Simple force-directed SVG network viz ----

interface NodePos {
  x: number
  y: number
  vx: number
  vy: number
  npi: string
  label: string
  risk: number
}

function layoutNodes(members: FraudRingMember[], edges: FraudRingEdge[], width: number, height: number): { nodes: NodePos[]; settled: boolean } {
  const cx = width / 2
  const cy = height / 2
  const nodes: NodePos[] = members.map((m, i) => {
    const angle = (2 * Math.PI * i) / members.length
    const r = Math.min(width, height) * 0.32
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      vx: 0,
      vy: 0,
      npi: m.npi,
      label: m.provider_name ? (m.provider_name.length > 18 ? m.provider_name.slice(0, 16) + '..' : m.provider_name) : m.npi.slice(-6),
      risk: m.risk_score,
    }
  })

  const npiIdx: Record<string, number> = {}
  nodes.forEach((n, i) => { npiIdx[n.npi] = i })

  // Run a few iterations of force simulation
  const iterations = 80
  for (let iter = 0; iter < iterations; iter++) {
    const alpha = 1 - iter / iterations

    // Repulsion between all pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = nodes[j].x - nodes[i].x
        let dy = nodes[j].y - nodes[i].y
        let dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (800 * alpha) / (dist * dist)
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        nodes[i].vx -= fx
        nodes[i].vy -= fy
        nodes[j].vx += fx
        nodes[j].vy += fy
      }
    }

    // Attraction along edges
    for (const e of edges) {
      const si = npiIdx[e.source]
      const ti = npiIdx[e.target]
      if (si === undefined || ti === undefined) continue
      let dx = nodes[ti].x - nodes[si].x
      let dy = nodes[ti].y - nodes[si].y
      let dist = Math.sqrt(dx * dx + dy * dy) || 1
      const force = (dist - 100) * 0.01 * alpha
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      nodes[si].vx += fx
      nodes[si].vy += fy
      nodes[ti].vx -= fx
      nodes[ti].vy -= fy
    }

    // Center gravity
    for (const n of nodes) {
      n.vx += (cx - n.x) * 0.01 * alpha
      n.vy += (cy - n.y) * 0.01 * alpha
    }

    // Apply velocity with damping
    for (const n of nodes) {
      n.vx *= 0.6
      n.vy *= 0.6
      n.x += n.vx
      n.y += n.vy
      // Clamp
      n.x = Math.max(40, Math.min(width - 40, n.x))
      n.y = Math.max(40, Math.min(height - 40, n.y))
    }
  }

  return { nodes, settled: true }
}

function NetworkViz({ members, edges }: { members: FraudRingMember[]; edges: FraudRingEdge[] }) {
  const width = 600
  const height = 400

  const { nodes } = useMemo(() => layoutNodes(members, edges, width, height), [members, edges])

  const npiPos: Record<string, NodePos> = {}
  nodes.forEach(n => { npiPos[n.npi] = n })

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto bg-gray-900/50 rounded-lg border border-gray-700">
      <defs>
        {Object.entries(CONNECTION_COLORS).map(([type, color]) => (
          <marker key={type} id={`arrow-${type}`} viewBox="0 0 10 10" refX="22" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={color} opacity={0.6} />
          </marker>
        ))}
      </defs>

      {/* Edges */}
      {edges.map((e, i) => {
        const s = npiPos[e.source]
        const t = npiPos[e.target]
        if (!s || !t) return null
        const color = CONNECTION_COLORS[e.type] || '#6b7280'
        return (
          <line
            key={i}
            x1={s.x} y1={s.y} x2={t.x} y2={t.y}
            stroke={color}
            strokeWidth={1.5}
            opacity={0.5}
            markerEnd={`url(#arrow-${e.type})`}
          >
            <title>{CONNECTION_LABELS[e.type] || e.type}: {e.detail}</title>
          </line>
        )
      })}

      {/* Nodes */}
      {nodes.map(n => {
        const r = n.risk >= 50 ? 14 : n.risk >= 25 ? 11 : 9
        const fill = n.risk >= 50 ? '#dc2626' : n.risk >= 25 ? '#f59e0b' : '#3b82f6'
        return (
          <g key={n.npi}>
            <circle cx={n.x} cy={n.y} r={r} fill={fill} opacity={0.85} stroke="#1f2937" strokeWidth={2} />
            <text x={n.x} y={n.y + r + 12} textAnchor="middle" fill="#9ca3af" fontSize={9} fontFamily="monospace">
              {n.label}
            </text>
            <title>{n.npi} - Risk: {n.risk}</title>
          </g>
        )
      })}

      {/* Legend */}
      {Object.entries(CONNECTION_LABELS).map(([type, label], i) => (
        <g key={type} transform={`translate(10, ${height - 10 - (Object.keys(CONNECTION_LABELS).length - i) * 14})`}>
          <line x1={0} y1={0} x2={16} y2={0} stroke={CONNECTION_COLORS[type]} strokeWidth={2} />
          <text x={20} y={4} fill="#9ca3af" fontSize={9}>{label}</text>
        </g>
      ))}
    </svg>
  )
}

// ---- Ring detail panel ----

function RingDetailPanel({ ringId, onClose }: { ringId: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['ring-detail', ringId],
    queryFn: () => api.fraudRingDetail(ringId),
  })

  if (isLoading) return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-6 mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-white">Ring Detail</h3>
        <button onClick={onClose} className="text-gray-500 hover:text-white">&times;</button>
      </div>
      <p className="text-gray-500 text-sm">Loading ring detail...</p>
    </div>
  )

  if (error || !data) return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-6 mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-white">Ring Detail</h3>
        <button onClick={onClose} className="text-gray-500 hover:text-white">&times;</button>
      </div>
      <p className="text-red-400 text-sm">Failed to load ring detail.</p>
    </div>
  )

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-6 mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-white">
          Ring Detail &mdash; {data.member_count} members
        </h3>
        <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">&times;</button>
      </div>

      {/* Network viz */}
      <div className="mb-6">
        <NetworkViz members={data.members} edges={data.edges} />
      </div>

      {/* Connection type badges */}
      <div className="flex flex-wrap gap-2 mb-4">
        {data.connection_types.map(t => (
          <span key={t} className="text-xs px-2 py-1 rounded-full border" style={{ borderColor: CONNECTION_COLORS[t] || '#6b7280', color: CONNECTION_COLORS[t] || '#6b7280' }}>
            {CONNECTION_LABELS[t] || t}
          </span>
        ))}
      </div>

      {/* Members table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b border-gray-700">
              <th className="text-left px-3 py-2 font-medium">NPI</th>
              <th className="text-left px-3 py-2 font-medium">Provider</th>
              <th className="text-left px-3 py-2 font-medium">Location</th>
              <th className="text-right px-3 py-2 font-medium">Risk</th>
              <th className="text-right px-3 py-2 font-medium">Billing</th>
              <th className="text-right px-3 py-2 font-medium">Claims</th>
              <th className="text-right px-3 py-2 font-medium">Flags</th>
            </tr>
          </thead>
          <tbody>
            {data.members.map((m: FraudRingMember) => (
              <tr key={m.npi} className="border-b border-gray-800 last:border-0 hover:bg-gray-700/30">
                <td className="px-3 py-2">
                  <Link to={`/providers/${m.npi}`} className="font-mono text-xs text-blue-400 hover:text-blue-300 underline">
                    {m.npi}
                  </Link>
                </td>
                <td className="px-3 py-2 text-gray-300 text-xs max-w-[200px] truncate" title={m.provider_name}>
                  {m.provider_name || '--'}
                </td>
                <td className="px-3 py-2 text-gray-500 text-xs">
                  {m.city && m.state ? `${m.city}, ${m.state}` : m.state || '--'}
                </td>
                <td className="px-3 py-2 text-right"><RiskBadge score={m.risk_score} /></td>
                <td className="px-3 py-2 text-right text-gray-400 text-xs font-mono">{fmt(m.total_paid)}</td>
                <td className="px-3 py-2 text-right text-gray-500 text-xs font-mono">{m.total_claims.toLocaleString()}</td>
                <td className="px-3 py-2 text-right">
                  {m.flag_count > 0
                    ? <span className="text-red-400 text-xs font-bold">{m.flag_count}</span>
                    : <span className="text-gray-600 text-xs">0</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edges list */}
      <details className="mt-4">
        <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-300">
          {data.edges.length} connections
        </summary>
        <div className="mt-2 max-h-48 overflow-y-auto">
          {data.edges.map((e: FraudRingEdge, i: number) => (
            <div key={i} className="flex items-center gap-2 text-xs text-gray-500 py-1 border-b border-gray-800 last:border-0">
              <span className="font-mono text-gray-400">{e.source.slice(-6)}</span>
              <span style={{ color: CONNECTION_COLORS[e.type] || '#6b7280' }}>&mdash;</span>
              <span className="font-mono text-gray-400">{e.target.slice(-6)}</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ color: CONNECTION_COLORS[e.type] || '#6b7280', borderColor: CONNECTION_COLORS[e.type] || '#6b7280', borderWidth: 1 }}>
                {CONNECTION_LABELS[e.type] || e.type}
              </span>
              <span className="text-gray-600 truncate max-w-[200px]" title={e.detail}>{e.detail}</span>
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}

// ---- Main page ----

export default function FraudRings() {
  const queryClient = useQueryClient()
  const [selectedRing, setSelectedRing] = useState<string | null>(null)
  const [detecting, setDetecting] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['fraud-rings'],
    queryFn: () => api.fraudRings(),
    refetchInterval: 30_000,
  })

  const handleDetect = useCallback(async () => {
    setDetecting(true)
    try {
      await api.detectRings()
      queryClient.invalidateQueries({ queryKey: ['fraud-rings'] })
    } catch (e) {
      console.error('Ring detection failed:', e)
    } finally {
      setDetecting(false)
    }
  }, [queryClient])

  const rings = data?.rings ?? []

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Fraud Ring Detection</h1>
          <p className="text-sm text-gray-500 mt-1">
            Identifies clusters of providers linked by shared addresses, phone numbers, billing NPIs, and beneficiaries
          </p>
        </div>
        <button
          onClick={handleDetect}
          disabled={detecting}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            detecting
              ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-500'
          }`}
        >
          {detecting ? 'Analyzing...' : 'Run Detection'}
        </button>
      </div>

      {/* Loading / empty states */}
      {isLoading && (
        <div className="text-center py-16">
          <div className="inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-gray-500 text-sm">Loading rings...</p>
        </div>
      )}

      {!isLoading && !data?.detected && (
        <div className="text-center py-16 bg-gray-800/50 rounded-lg border border-gray-700">
          <svg className="mx-auto w-12 h-12 text-gray-600 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <h3 className="text-gray-400 font-medium mb-2">No detection results yet</h3>
          <p className="text-gray-600 text-sm mb-4">Click "Run Detection" to analyze provider relationships and identify potential fraud rings.</p>
        </div>
      )}

      {!isLoading && data?.detected && rings.length === 0 && (
        <div className="text-center py-16 bg-gray-800/50 rounded-lg border border-gray-700">
          <h3 className="text-green-400 font-medium mb-2">No fraud rings detected</h3>
          <p className="text-gray-600 text-sm">No suspicious provider clusters were found in the current dataset.</p>
        </div>
      )}

      {/* KPI row */}
      {rings.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Rings Found</div>
            <div className="text-2xl font-bold text-white">{rings.length}</div>
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Total Providers</div>
            <div className="text-2xl font-bold text-white">{rings.reduce((s, r) => s + r.member_count, 0)}</div>
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Total Billing</div>
            <div className="text-2xl font-bold text-amber-400">{fmt(rings.reduce((s, r) => s + r.total_paid, 0))}</div>
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Highest Suspicion</div>
            <div className="text-2xl font-bold text-red-400">{rings.length > 0 ? rings[0].suspicion_score.toFixed(0) : '--'}</div>
          </div>
        </div>
      )}

      {/* Ring cards */}
      {rings.length > 0 && (
        <div className="space-y-3">
          {rings.map((ring) => (
            <div key={ring.ring_id}>
              <button
                onClick={() => setSelectedRing(selectedRing === ring.ring_id ? null : ring.ring_id)}
                className={`w-full text-left bg-gray-800 border rounded-lg p-4 transition-colors hover:bg-gray-750 ${
                  selectedRing === ring.ring_id ? 'border-blue-500' : 'border-gray-700'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    {/* Suspicion badge */}
                    <div className={`w-12 h-12 rounded-lg flex items-center justify-center text-lg font-bold ${
                      ring.suspicion_score >= 80
                        ? 'bg-red-900/60 text-red-300'
                        : ring.suspicion_score >= 40
                          ? 'bg-orange-900/60 text-orange-300'
                          : 'bg-yellow-900/60 text-yellow-300'
                    }`}>
                      {ring.suspicion_score.toFixed(0)}
                    </div>

                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-white font-medium">{ring.member_count} providers</span>
                        {ring.high_risk_count > 0 && (
                          <span className="text-xs bg-red-900/50 text-red-400 px-2 py-0.5 rounded">
                            {ring.high_risk_count} high-risk
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-gray-500">Billing: <span className="text-gray-300 font-mono">{fmt(ring.total_paid)}</span></span>
                        <span className="text-xs text-gray-500">Avg Risk: <span className="text-gray-300 font-mono">{ring.avg_risk_score.toFixed(1)}</span></span>
                        <span className="text-xs text-gray-500">Density: <span className="text-gray-300 font-mono">{(ring.density * 100).toFixed(0)}%</span></span>
                        <span className="text-xs text-gray-500">Flags: <span className="text-gray-300 font-mono">{ring.total_flags}</span></span>
                      </div>
                    </div>
                  </div>

                  {/* Connection type pills */}
                  <div className="flex items-center gap-2">
                    {ring.connection_types.map(t => (
                      <span
                        key={t}
                        className="text-[10px] px-2 py-0.5 rounded-full border"
                        style={{ borderColor: CONNECTION_COLORS[t] || '#6b7280', color: CONNECTION_COLORS[t] || '#6b7280' }}
                      >
                        {CONNECTION_LABELS[t] || t}
                      </span>
                    ))}
                    <svg className={`w-4 h-4 text-gray-500 transition-transform ${selectedRing === ring.ring_id ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>
              </button>

              {/* Expanded detail */}
              {selectedRing === ring.ring_id && (
                <RingDetailPanel ringId={ring.ring_id} onClose={() => setSelectedRing(null)} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
