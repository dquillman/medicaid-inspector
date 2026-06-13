import { useState, lazy, Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import NetworkGraphCanvas from '../components/NetworkGraphCanvas'
import { isWebGLAvailable } from '../lib/webgl'

const NetworkGraph3D = lazy(() => import('../components/NetworkGraph3D'))

export default function NetworkGraph() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [npiInput, setNpiInput] = useState(searchParams.get('npi') ?? '')
  const [activeNpi, setActiveNpi] = useState(searchParams.get('npi') ?? '')
  const [view3d, setView3d] = useState(false)
  const [webglOk] = useState(() => typeof window !== 'undefined' && isWebGLAvailable())

  const { data, isLoading, error } = useQuery({
    queryKey: ['network', activeNpi],
    queryFn: () => api.network(activeNpi),
    enabled: activeNpi.length >= 10,
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setActiveNpi(npiInput.trim())
  }

  return (
    <div className="space-y-4 h-full">
      <div>
        <h1 className="text-2xl font-bold text-white">Provider Network</h1>
        <p className="text-gray-400 text-sm mt-1">
          Billing &#8596; servicing relationships for a given NPI. Node size = total paid; color = risk level.
        </p>
        <p className="text-gray-500 text-xs mt-1">
          Visualizing billing relationships between providers. Lines indicate shared servicing arrangements.
        </p>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="card flex gap-3 items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">NPI Number</label>
          <input
            className="input w-56"
            placeholder="10-digit NPI…"
            value={npiInput}
            onChange={e => setNpiInput(e.target.value)}
            maxLength={10}
          />
        </div>
        <button type="submit" className="btn-primary" disabled={npiInput.length < 10}>
          Load Network
        </button>
        {activeNpi && data && (
          <span className="text-ink-tertiary text-sm self-center font-mono tabular-nums">
            {data.nodes.length} nodes · {data.edges.length} edges
          </span>
        )}
        {webglOk && (
          <div className="ml-auto self-center inline-flex rounded-lg border border-hairline overflow-hidden text-xs font-mono uppercase tracking-wider">
            <button
              type="button"
              onClick={() => setView3d(false)}
              className={`px-3 py-1.5 transition-colors ${!view3d ? 'bg-filament-core/15 text-filament-core' : 'text-ink-tertiary hover:text-ink-secondary'}`}
            >
              2D
            </button>
            <button
              type="button"
              onClick={() => setView3d(true)}
              className={`px-3 py-1.5 transition-colors border-l border-hairline ${view3d ? 'bg-filament-core/15 text-filament-core' : 'text-ink-tertiary hover:text-ink-secondary'}`}
            >
              3D
            </button>
          </div>
        )}
      </form>

      {/* Graph canvas */}
      <div className="card p-0 overflow-hidden" style={{ height: 560 }}>
        {!activeNpi && (
          <div className="h-full flex items-center justify-center text-gray-600 text-sm">
            Enter an NPI above to explore its billing network.
          </div>
        )}
        {activeNpi && isLoading && (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            Querying billing relationships…
          </div>
        )}
        {error && (
          <div className="h-full flex items-center justify-center text-red-400 text-sm p-8 text-center">
            {String(error)}
          </div>
        )}
        {data && !isLoading && (
          <NetworkGraphCanvas
            graph={data}
            onNodeClick={npi => navigate(`/providers/${npi}`)}
          />
        )}
      </div>

      {/* Node legend */}
      {data && (
        <div className="card flex items-center gap-6 text-xs text-gray-400">
          <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-blue-500 inline-block" /> Center NPI</div>
          <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> High risk</div>
          <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-yellow-500 inline-block" /> Medium risk</div>
          <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-green-500 inline-block" /> Low risk</div>
          <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-gray-500 inline-block" /> Unscored</div>
          <span className="ml-auto text-gray-600">Click any node to view provider detail</span>
        </div>
      )}
    </div>
  )
}
