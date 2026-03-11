import { Link } from 'react-router-dom'
import type { OwnershipChain } from '../lib/types'
import { fmt } from '../lib/format'

function riskColor(score: number) {
  if (score >= 50) return { bg: 'bg-red-900', text: 'text-red-300', border: 'border-red-700', ring: 'ring-red-500/30' }
  if (score >= 25) return { bg: 'bg-orange-900', text: 'text-orange-300', border: 'border-orange-700', ring: 'ring-orange-500/30' }
  return { bg: 'bg-green-900', text: 'text-green-300', border: 'border-green-700', ring: 'ring-green-500/30' }
}

export default function OwnershipNetwork({ data, currentNpi }: { data: OwnershipChain; currentNpi?: string }) {
  if (!data.official || data.controlled_npis.length === 0) return null

  const { official, controlled_npis, shared_addresses } = data

  // Build a set of NPIs that share addresses for highlighting
  const sharedNpis = new Set<string>()
  const npiToSharedGroup = new Map<string, number>()
  shared_addresses.forEach((sa, idx) => {
    sa.npis.forEach(n => {
      sharedNpis.add(n)
      npiToSharedGroup.set(n, idx)
    })
  })

  const groupColors = [
    'border-l-cyan-500',
    'border-l-purple-500',
    'border-l-pink-500',
    'border-l-teal-500',
    'border-l-amber-500',
  ]

  return (
    <div className="space-y-4">
      {/* Central official node */}
      <div className="flex justify-center">
        <div className="bg-blue-950 border-2 border-blue-600 rounded-xl px-6 py-3 text-center shadow-lg shadow-blue-950/50">
          <div className="text-xs text-blue-400 uppercase tracking-wider font-semibold mb-1">Authorized Official</div>
          <div className="text-white font-bold text-base">{official.name}</div>
          {official.title && <div className="text-blue-300 text-xs mt-0.5">{official.title}</div>}
          <div className="text-blue-400 text-xs mt-1.5 font-mono">
            Controls {controlled_npis.length} entit{controlled_npis.length === 1 ? 'y' : 'ies'}
          </div>
        </div>
      </div>

      {/* Connection lines visual */}
      <div className="flex justify-center">
        <div className="w-px h-6 bg-gray-600" />
      </div>

      {/* NPI nodes in a grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {controlled_npis.map(node => {
          const rc = riskColor(node.risk_score)
          const isCurrent = node.npi === currentNpi
          const groupIdx = npiToSharedGroup.get(node.npi)
          const groupColor = groupIdx !== undefined ? groupColors[groupIdx % groupColors.length] : ''

          return (
            <div
              key={node.npi}
              className={`rounded-lg border px-4 py-3 transition-all ${
                isCurrent
                  ? 'border-blue-500 bg-blue-950/40 ring-2 ring-blue-500/30'
                  : `border-gray-700 bg-gray-800/50 hover:bg-gray-800`
              } ${groupColor ? `border-l-4 ${groupColor}` : ''}`}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="min-w-0 flex-1">
                  <Link
                    to={`/providers/${node.npi}`}
                    className="font-mono text-xs text-blue-400 hover:text-blue-300 underline"
                  >
                    {node.npi}
                  </Link>
                  <div className="text-sm text-gray-200 truncate mt-0.5" title={node.name}>
                    {node.name || '--'}
                  </div>
                </div>
                <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${rc.bg} ${rc.text}`}>
                  {node.risk_score.toFixed(0)}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <div>
                  <span className="text-gray-500">Paid: </span>
                  <span className="text-gray-300 font-mono">{fmt(node.total_paid)}</span>
                </div>
                <div>
                  <span className="text-gray-500">Flags: </span>
                  <span className={node.flag_count > 0 ? 'text-red-400' : 'text-gray-500'}>
                    {node.flag_count}
                  </span>
                </div>
                <div className="col-span-2 truncate" title={node.specialty}>
                  <span className="text-gray-500">Specialty: </span>
                  <span className="text-gray-400">{node.specialty || '--'}</span>
                </div>
                {node.entity_type && (
                  <div className="col-span-2">
                    <span className="text-gray-500">Type: </span>
                    <span className="text-gray-400">
                      {node.entity_type === 'NPI-2' ? 'Organization' : 'Individual'}
                    </span>
                  </div>
                )}
              </div>

              {isCurrent && (
                <div className="mt-2 text-[10px] text-blue-400 uppercase tracking-wider font-semibold">
                  Current Provider
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Shared address legend */}
      {shared_addresses.length > 0 && (
        <div className="border border-gray-700 rounded-lg px-4 py-3 bg-gray-800/30">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Shared Addresses ({shared_addresses.length})
          </h3>
          <div className="space-y-1.5">
            {shared_addresses.map((sa, idx) => (
              <div key={idx} className="flex items-center gap-2 text-xs">
                <div className={`w-3 h-3 rounded-sm ${
                  ['bg-cyan-500', 'bg-purple-500', 'bg-pink-500', 'bg-teal-500', 'bg-amber-500'][idx % 5]
                }`} />
                <span className="text-gray-400">{sa.address}</span>
                <span className="text-gray-600">--</span>
                <span className="text-gray-500">{sa.npis.length} NPIs</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
