import type { ScoredProvider } from '../lib/types'

interface BulkActionBarProps {
  selectedNpis: Set<string>
  providers: ScoredProvider[]
  onClearSelection: () => void
  onAddToReviewQueue: () => void
}

export default function BulkActionBar({
  selectedNpis,
  providers,
  onClearSelection,
  onAddToReviewQueue,
}: BulkActionBarProps) {
  if (selectedNpis.size === 0) return null

  const handleExportCSV = () => {
    const selected = providers.filter(p => selectedNpis.has(p.npi))
    if (selected.length === 0) return

    const headers = [
      'NPI', 'Provider Name', 'Risk Score', 'Flags', 'State', 'City',
      'Total Paid', 'Claims', 'Beneficiaries', 'Months Active',
    ]

    const rows = selected.map(p => [
      p.npi,
      (p.provider_name ?? '').replace(/,/g, ' '),
      String(p.risk_score),
      String(p.flags.length),
      p.state ?? '',
      p.city ?? '',
      String(p.total_paid),
      String(p.total_claims),
      String(p.total_beneficiaries),
      String(p.active_months),
    ])

    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `providers_export_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-gray-800 border-t border-gray-700 px-6 py-3 z-30 flex items-center gap-4">
      <span className="text-sm text-gray-200 font-medium">
        {selectedNpis.size} provider{selectedNpis.size !== 1 ? 's' : ''} selected
      </span>
      <button className="btn-primary text-sm" onClick={onAddToReviewQueue}>
        Add to Review Queue
      </button>
      <button className="btn-ghost text-sm" onClick={handleExportCSV}>
        Export CSV
      </button>
      <button className="btn-ghost text-sm" onClick={onClearSelection}>
        Clear Selection
      </button>
    </div>
  )
}
