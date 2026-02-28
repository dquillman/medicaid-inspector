import { useState } from 'react'
import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import { scaleSequential } from 'd3-scale'
import { interpolateReds } from 'd3-scale-chromatic'

const GEO_URL = 'https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json'

interface StateData {
  state: string
  flagged_count: number
  total_paid: number
  provider_count: number
}

interface Props {
  data: StateData[]
  onStateClick?: (state: string) => void
}

function fmtM(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`
  return `$${v}`
}

// FIPS → state abbreviation mapping (subset, enough for heatmap)
const FIPS_STATE: Record<string, string> = {
  '01':'AL','02':'AK','04':'AZ','05':'AR','06':'CA','08':'CO','09':'CT',
  '10':'DE','11':'DC','12':'FL','13':'GA','15':'HI','16':'ID','17':'IL',
  '18':'IN','19':'IA','20':'KS','21':'KY','22':'LA','23':'ME','24':'MD',
  '25':'MA','26':'MI','27':'MN','28':'MS','29':'MO','30':'MT','31':'NE',
  '32':'NV','33':'NH','34':'NJ','35':'NM','36':'NY','37':'NC','38':'ND',
  '39':'OH','40':'OK','41':'OR','42':'PA','44':'RI','45':'SC','46':'SD',
  '47':'TN','48':'TX','49':'UT','50':'VT','51':'VA','53':'WA','54':'WV',
  '55':'WI','56':'WY',
}

export default function StateHeatmap({ data, onStateClick }: Props) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; d: StateData; abbr: string } | null>(null)

  const stateMap = Object.fromEntries(data.map(d => [d.state, d]))
  const maxFlagged = Math.max(...data.map(d => d.flagged_count), 1)
  const colorScale = scaleSequential([0, maxFlagged], interpolateReds)

  if (data.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-gray-600 text-sm">
        <span className="text-2xl">🗺️</span>
        <p>Waiting for provider data…</p>
        <p className="text-xs text-gray-700">State data populates after NPPES enrichment completes</p>
      </div>
    )
  }

  return (
    <div className="relative h-full w-full">
      <ComposableMap
        projection="geoAlbersUsa"
        style={{ width: '100%', height: '100%' }}
      >
        <Geographies geography={GEO_URL}>
          {({ geographies }) =>
            geographies.map(geo => {
              const fips = geo.id as string
              const abbr = FIPS_STATE[fips] ?? ''
              const d = stateMap[abbr]
              const fill = d ? colorScale(d.flagged_count) : '#1f2937'
              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill={fill}
                  stroke="#374151"
                  strokeWidth={0.5}
                  style={{
                    default: { outline: 'none', cursor: d ? 'pointer' : 'default' },
                    hover:   { outline: 'none', opacity: 0.75 },
                    pressed: { outline: 'none' },
                  }}
                  onMouseEnter={(e) => {
                    if (!d) return
                    setTooltip({ x: e.clientX, y: e.clientY, d, abbr })
                  }}
                  onMouseMove={(e) => {
                    if (!d) return
                    setTooltip(prev => prev ? { ...prev, x: e.clientX, y: e.clientY } : null)
                  }}
                  onMouseLeave={() => setTooltip(null)}
                  onClick={() => {
                    if (d && onStateClick) onStateClick(abbr)
                  }}
                />
              )
            })
          }
        </Geographies>
      </ComposableMap>

      {tooltip && (
        <div
          className="fixed z-50 pointer-events-none bg-gray-900 border border-gray-700 rounded-lg shadow-xl px-3 py-2 text-xs space-y-1"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
        >
          <div className="font-bold text-white text-sm">{tooltip.abbr}</div>
          <div className="flex items-center gap-2">
            <span className="text-red-400 font-semibold">{tooltip.d.flagged_count.toLocaleString()}</span>
            <span className="text-gray-400">flagged providers</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-blue-400 font-semibold">{fmtM(tooltip.d.total_paid)}</span>
            <span className="text-gray-400">total paid</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-300">{tooltip.d.provider_count.toLocaleString()}</span>
            <span className="text-gray-400">providers scanned</span>
          </div>
        </div>
      )}
    </div>
  )
}
