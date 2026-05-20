import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, get } from '../lib/api'

interface NarrativeSection {
  title: string
  content: string
}

interface NarrativeData {
  narrative: string
  sections: NarrativeSection[]
  generated_at: string
  word_count: number
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export default function InvestigatePage() {
  const { npi } = useParams<{ npi: string }>()

  const { data: provider } = useQuery({
    queryKey: ['provider', npi],
    queryFn: () => api.providerDetail(npi!),
    enabled: !!npi,
  })

  const {
    data: narrative,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['narrative', npi],
    queryFn: () => get<NarrativeData>(`/providers/${npi}/narrative`),
    enabled: !!npi,
  })

  const providerName = provider?.nppes?.name || provider?.provider_name || `NPI ${npi}`

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/providers" className="hover:text-gray-300">Providers</Link>
        <span>/</span>
        <Link to={`/providers/${npi}`} className="hover:text-gray-300">{npi}</Link>
        <span>/</span>
        <span className="text-gray-400">Investigation Narrative</span>
      </div>

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Investigation Narrative</h1>
          <p className="text-gray-400 text-sm mt-1">{providerName}</p>
        </div>
        <div className="flex items-center gap-3 no-print">
          <button
            onClick={() => window.print()}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-300 text-xs rounded transition-colors"
          >
            Print
          </button>
          <Link
            to={`/providers/${npi}`}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-300 text-xs rounded transition-colors"
          >
            Back to Provider
          </Link>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-400 text-sm mt-4">Generating investigation narrative...</p>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-xl p-5 text-center">
          <p className="text-red-400 text-sm">
            {error instanceof Error ? error.message : 'Failed to load narrative'}
          </p>
        </div>
      )}

      {/* Content */}
      {narrative && !isLoading && (
        <div className="space-y-5">
          {/* Summary card */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-5">
            <h2 className="text-gray-200 font-semibold text-sm mb-3">Summary</h2>
            <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-line">
              {narrative.narrative}
            </p>
          </div>

          {/* Sections */}
          {narrative.sections.length > 0 &&
            narrative.sections.map((section, i) => (
              <div
                key={i}
                className="bg-gray-800/50 border border-gray-700 rounded-xl p-5"
              >
                <h2 className="text-gray-200 font-semibold mb-3">{section.title}</h2>
                <p className="text-gray-400 text-sm leading-relaxed whitespace-pre-line">
                  {section.content}
                </p>
              </div>
            ))}

          {/* Metadata footer */}
          <div className="flex items-center justify-between text-xs text-gray-600 border-t border-gray-800 pt-3">
            <span>Generated: {formatDate(narrative.generated_at)}</span>
            <span>{narrative.word_count.toLocaleString()} words</span>
          </div>
        </div>
      )}
    </div>
  )
}
