import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import StateHeatmap from '../components/StateHeatmap'
import { fmtM } from '../lib/format'

function SeverityBadge({ count }: { count: number }) {
  if (count >= 10) {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-900/60 text-red-300 border border-red-700">
        Critical
      </span>
    )
  }
  if (count >= 5) {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-orange-900/60 text-orange-300 border border-orange-700">
        High
      </span>
    )
  }
  if (count >= 3) {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-yellow-900/60 text-yellow-300 border border-yellow-700">
        Watch
      </span>
    )
  }
  return null
}

function RiskBar({ score }: { score: number }) {
  const color =
    score >= 50 ? 'bg-red-500' : score >= 30 ? 'bg-orange-500' : score >= 10 ? 'bg-yellow-500' : 'bg-green-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(score, 100)}%` }} />
      </div>
      <span className="text-xs text-gray-400">{score}</span>
    </div>
  )
}

type Tab = 'hotspots' | 'by-zip' | 'by-city'

export default function GeographicAnalysis() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('hotspots')
  const [selectedState, setSelectedState] = useState<string | null>(null)

  const { data: heatmapData } = useQuery({
    queryKey: ['state-heatmap'],
    queryFn: api.stateHeatmap,
    refetchInterval: 120000,
  })

  const { data: hotspotsData, isLoading: hotspotsLoading } = useQuery({
    queryKey: ['geo-hotspots'],
    queryFn: api.geographyHotspots,
  })

  const { data: zipData, isLoading: zipLoading } = useQuery({
    queryKey: ['geo-by-zip'],
    queryFn: api.geographyByZip,
    enabled: tab === 'by-zip',
  })

  const { data: cityData, isLoading: cityLoading } = useQuery({
    queryKey: ['geo-by-city'],
    queryFn: api.geographyByCity,
    enabled: tab === 'by-city',
  })

  const { data: drilldownData, isLoading: drilldownLoading } = useQuery({
    queryKey: ['geo-state-drilldown', selectedState],
    queryFn: () => api.geographyStateDrilldown(selectedState!),
    enabled: !!selectedState,
  })

  const handleStateClick = (state: string) => {
    setSelectedState(state)
  }

  const handleBackFromDrilldown = () => {
    setSelectedState(null)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Geographic Analysis</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Fraud hotspot detection and geographic drill-down by state, city, and ZIP code
          </p>
        </div>
        {selectedState && (
          <button onClick={handleBackFromDrilldown} className="btn-ghost text-sm flex items-center gap-1.5">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Back to national view
          </button>
        )}
      </div>

      {/* State Heatmap */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-300">
            {selectedState ? `${selectedState} — State Detail` : 'Flagged Providers by State'}
          </h2>
          <span className="text-xs text-gray-600">Click a state to drill down</span>
        </div>
        <div className="h-[320px]">
          <StateHeatmap data={heatmapData?.by_state ?? []} onStateClick={handleStateClick} />
        </div>
      </div>

      {/* State Drilldown */}
      {selectedState && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">
              Cities in {selectedState}
            </h2>
            {drilldownData && (
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span>{drilldownData.total_providers.toLocaleString()} providers</span>
                <span className="text-red-400">{drilldownData.total_flagged.toLocaleString()} flagged</span>
                <span>{fmtM(drilldownData.total_paid)} total paid</span>
              </div>
            )}
          </div>
          {drilldownLoading ? (
            <div className="text-center py-8 text-gray-600 text-sm">Loading city data...</div>
          ) : drilldownData?.cities.length === 0 ? (
            <div className="text-center py-8 text-gray-600 text-sm">No providers found in {selectedState}</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
                    <th className="py-2 pr-4">City</th>
                    <th className="py-2 pr-4 text-right">Providers</th>
                    <th className="py-2 pr-4 text-right">Flagged</th>
                    <th className="py-2 pr-4 text-right">Total Paid</th>
                    <th className="py-2 pr-4">Avg Risk</th>
                    <th className="py-2 pr-4">Severity</th>
                    <th className="py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {drilldownData?.cities.map((c) => (
                    <tr key={`${c.city}-${c.state}`} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="py-2 pr-4 font-medium text-gray-200">{c.city}</td>
                      <td className="py-2 pr-4 text-right text-gray-400">{c.provider_count.toLocaleString()}</td>
                      <td className="py-2 pr-4 text-right">
                        <span className={c.flagged_count > 0 ? 'text-red-400 font-semibold' : 'text-gray-600'}>
                          {c.flagged_count}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-right text-gray-400">{fmtM(c.total_paid)}</td>
                      <td className="py-2 pr-4">
                        <RiskBar score={c.avg_risk_score} />
                      </td>
                      <td className="py-2 pr-4">
                        <SeverityBadge count={c.flagged_count} />
                      </td>
                      <td className="py-2">
                        <button
                          onClick={() => navigate(`/providers?cities=${encodeURIComponent(c.city)}&states=${c.state}`)}
                          className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
                        >
                          View providers
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tabs for national tables */}
      {!selectedState && (
        <>
          <div className="flex gap-1 border-b border-gray-800 pb-px">
            {([
              { key: 'hotspots' as Tab, label: 'Fraud Hotspots' },
              { key: 'by-zip' as Tab, label: 'Top ZIP Codes' },
              { key: 'by-city' as Tab, label: 'Top Cities' },
            ]).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={
                  tab === key
                    ? 'px-4 py-2 text-sm font-semibold text-white border-b-2 border-blue-500 -mb-px'
                    : 'px-4 py-2 text-sm text-gray-500 hover:text-gray-300'
                }
              >
                {label}
                {key === 'hotspots' && hotspotsData?.hotspots?.length
                  ? ` (${hotspotsData.hotspots.length})`
                  : ''}
              </button>
            ))}
          </div>

          {/* Hotspots Tab */}
          {tab === 'hotspots' && (
            <div className="card">
              {hotspotsLoading ? (
                <div className="text-center py-8 text-gray-600 text-sm">Analyzing hotspots...</div>
              ) : !hotspotsData?.hotspots?.length ? (
                <div className="text-center py-8 text-gray-600 text-sm">
                  No fraud hotspots detected. Hotspots require ZIP areas with 5+ flagged providers and avg risk &gt; 30.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
                        <th className="py-2 pr-4">Severity</th>
                        <th className="py-2 pr-4">ZIP Area</th>
                        <th className="py-2 pr-4">Region</th>
                        <th className="py-2 pr-4 text-right">Providers</th>
                        <th className="py-2 pr-4 text-right">Flagged</th>
                        <th className="py-2 pr-4 text-right">Total Paid</th>
                        <th className="py-2 pr-4">Avg Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hotspotsData.hotspots.map((h) => (
                        <tr key={h.zip3} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                          <td className="py-2 pr-4">
                            <SeverityBadge count={h.flagged_count} />
                          </td>
                          <td className="py-2 pr-4 font-mono text-gray-200">{h.zip3}xx</td>
                          <td className="py-2 pr-4 text-gray-400 text-xs">
                            {h.states.join(', ')}
                            {h.cities.length > 0 && (
                              <span className="block text-gray-600 mt-0.5">{h.cities.join(', ')}</span>
                            )}
                          </td>
                          <td className="py-2 pr-4 text-right text-gray-400">{h.provider_count.toLocaleString()}</td>
                          <td className="py-2 pr-4 text-right text-red-400 font-semibold">
                            {h.flagged_count}
                          </td>
                          <td className="py-2 pr-4 text-right text-gray-400">{fmtM(h.total_paid)}</td>
                          <td className="py-2 pr-4">
                            <RiskBar score={h.avg_risk_score} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* By ZIP Tab */}
          {tab === 'by-zip' && (
            <div className="card">
              {zipLoading ? (
                <div className="text-center py-8 text-gray-600 text-sm">Loading ZIP data...</div>
              ) : !zipData?.by_zip?.length ? (
                <div className="text-center py-8 text-gray-600 text-sm">No ZIP code data available</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
                        <th className="py-2 pr-4">#</th>
                        <th className="py-2 pr-4">ZIP Area</th>
                        <th className="py-2 pr-4 text-right">Providers</th>
                        <th className="py-2 pr-4 text-right">Flagged</th>
                        <th className="py-2 pr-4 text-right">Total Paid</th>
                        <th className="py-2 pr-4">Avg Risk</th>
                        <th className="py-2">Severity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {zipData.by_zip.map((z, i) => (
                        <tr key={z.zip3} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                          <td className="py-2 pr-4 text-gray-600 text-xs">{i + 1}</td>
                          <td className="py-2 pr-4 font-mono text-gray-200">{z.zip3}xx</td>
                          <td className="py-2 pr-4 text-right text-gray-400">{z.provider_count.toLocaleString()}</td>
                          <td className="py-2 pr-4 text-right">
                            <span className={z.flagged_count > 0 ? 'text-red-400 font-semibold' : 'text-gray-600'}>
                              {z.flagged_count}
                            </span>
                          </td>
                          <td className="py-2 pr-4 text-right text-gray-400">{fmtM(z.total_paid)}</td>
                          <td className="py-2 pr-4">
                            <RiskBar score={z.avg_risk_score} />
                          </td>
                          <td className="py-2">
                            <SeverityBadge count={z.flagged_count} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* By City Tab */}
          {tab === 'by-city' && (
            <div className="card">
              {cityLoading ? (
                <div className="text-center py-8 text-gray-600 text-sm">Loading city data...</div>
              ) : !cityData?.by_city?.length ? (
                <div className="text-center py-8 text-gray-600 text-sm">No city data available</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
                        <th className="py-2 pr-4">#</th>
                        <th className="py-2 pr-4">City</th>
                        <th className="py-2 pr-4">State</th>
                        <th className="py-2 pr-4 text-right">Providers</th>
                        <th className="py-2 pr-4 text-right">Flagged</th>
                        <th className="py-2 pr-4 text-right">Total Paid</th>
                        <th className="py-2 pr-4">Avg Risk</th>
                        <th className="py-2 pr-4">Severity</th>
                        <th className="py-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cityData.by_city.map((c, i) => (
                        <tr key={`${c.city}-${c.state}`} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                          <td className="py-2 pr-4 text-gray-600 text-xs">{i + 1}</td>
                          <td className="py-2 pr-4 font-medium text-gray-200">{c.city}</td>
                          <td className="py-2 pr-4 text-gray-400">{c.state}</td>
                          <td className="py-2 pr-4 text-right text-gray-400">{c.provider_count.toLocaleString()}</td>
                          <td className="py-2 pr-4 text-right">
                            <span className={c.flagged_count > 0 ? 'text-red-400 font-semibold' : 'text-gray-600'}>
                              {c.flagged_count}
                            </span>
                          </td>
                          <td className="py-2 pr-4 text-right text-gray-400">{fmtM(c.total_paid)}</td>
                          <td className="py-2 pr-4">
                            <RiskBar score={c.avg_risk_score} />
                          </td>
                          <td className="py-2 pr-4">
                            <SeverityBadge count={c.flagged_count} />
                          </td>
                          <td className="py-2">
                            <button
                              onClick={() => navigate(`/providers?cities=${encodeURIComponent(c.city)}&states=${c.state}`)}
                              className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
                            >
                              View providers
                            </button>
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
    </div>
  )
}
