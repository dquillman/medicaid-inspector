import { useEffect, useState, useCallback } from 'react'
import { get } from '../lib/api'

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

interface InvestigateModalProps {
  npi: string
  providerName: string
  onClose: () => void
}

export default function InvestigateModal({ npi, providerName, onClose }: InvestigateModalProps) {
  const [data, setData] = useState<NarrativeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSections, setExpandedSections] = useState<Set<number>>(new Set())

  // Fetch narrative on mount
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    get<NarrativeData>(`/providers/${npi}/narrative`)
      .then(res => {
        if (!cancelled) {
          setData(res)
          setLoading(false)
        }
      })
      .catch(err => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load narrative')
          setLoading(false)
        }
      })

    return () => { cancelled = true }
  }, [npi])

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  const toggleSection = useCallback((index: number) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }, [])

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose()
    },
    [onClose],
  )

  const formatDate = (iso: string): string => {
    try {
      return new Date(iso).toLocaleString()
    } catch {
      return iso
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/60 z-50 overflow-y-auto"
      onClick={handleBackdropClick}
    >
      <div className="max-w-4xl mx-auto mt-16 mb-8">
        <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl max-h-[80vh] overflow-y-auto modal-pop elev-3">
          {/* Header */}
          <div className="sticky top-0 bg-gray-900 border-b border-gray-700 px-6 py-4 flex items-center justify-between z-10">
            <div className="min-w-0">
              <h2 className="text-white font-bold text-lg truncate">
                Investigation Narrative &mdash; NPI {npi}
              </h2>
              <p className="text-gray-400 text-sm mt-0.5 truncate">{providerName}</p>
            </div>
            <div className="flex items-center gap-3 shrink-0 ml-4">
              <button
                onClick={() => window.print()}
                className="px-3 py-1.5 text-sm font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              >
                Print
              </button>
              <button
                onClick={onClose}
                className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2 transition-colors"
                title="Close"
              >
                &#x2715;
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="p-6">
            {/* Loading state */}
            {loading && (
              <div className="flex flex-col items-center justify-center py-20">
                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-400 text-sm mt-4">Generating investigation narrative...</p>
              </div>
            )}

            {/* Error state */}
            {error && !loading && (
              <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-center">
                <p className="text-red-400 text-sm">{error}</p>
                <button
                  onClick={onClose}
                  className="mt-3 text-xs text-gray-500 hover:text-gray-300 underline transition-colors"
                >
                  Close
                </button>
              </div>
            )}

            {/* Success state */}
            {data && !loading && (
              <div className="space-y-5">
                {/* Full narrative */}
                <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
                  <h3 className="text-gray-200 font-semibold text-sm mb-2">Summary</h3>
                  <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-line">
                    {data.narrative}
                  </p>
                </div>

                {/* Expandable sections */}
                {data.sections.length > 0 && (
                  <div>
                    <h3 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">
                      Detailed Sections
                    </h3>
                    {data.sections.map((section, i) => {
                      const isExpanded = expandedSections.has(i)
                      return (
                        <div
                          key={i}
                          className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-3"
                        >
                          <button
                            onClick={() => toggleSection(i)}
                            className="w-full flex items-center justify-between text-left group"
                          >
                            <span className="text-gray-200 font-medium text-sm group-hover:text-white transition-colors">
                              {section.title}
                            </span>
                            <span
                              className={`text-gray-500 text-xs transition-transform duration-200 ${
                                isExpanded ? 'rotate-180' : ''
                              }`}
                            >
                              &#x25BC;
                            </span>
                          </button>
                          {isExpanded && (
                            <p className="text-gray-400 text-sm leading-relaxed mt-3 whitespace-pre-line">
                              {section.content}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* Metadata footer */}
                <div className="flex items-center justify-between text-xs text-gray-600 border-t border-gray-800 pt-3">
                  <span>Generated: {formatDate(data.generated_at)}</span>
                  <span>{data.word_count.toLocaleString()} words</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
