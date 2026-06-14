import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { threatColor } from '../lib/threat'
import Breadcrumbs from '../components/Breadcrumbs'
import ProviderFlags from '../components/ProviderFlags'

export default function Excluded() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['excluded-providers'],
    queryFn: () => api.excludedProviders(),
    staleTime: 10 * 60_000,
  })

  return (
    <div className="space-y-5">
      <Breadcrumbs />

      <div>
        <h1 className="text-xl font-bold text-gray-200">Excluded Providers</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-3xl">
          Providers on the federal OIG LEIE exclusion list. They are barred from
          billing the program and are removed from the Providers list, Anomalies,
          Review Queue, and Fraud Brain — this page is their single home.
          Any Medicaid payments shown here were made to an excluded entity.
        </p>
      </div>

      {data && (
        <div className="grid grid-cols-2 gap-4 max-w-xl">
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Excluded Providers</p>
            <p className="text-xl font-bold text-red-400">{data.total.toLocaleString()}</p>
          </div>
          <div className="card py-3">
            <p className="text-[10px] text-gray-600 uppercase tracking-wider">Total Paid While in Dataset</p>
            <p className="text-xl font-bold text-red-400">{fmt(data.total_paid)}</p>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="card h-32 flex items-center justify-center text-gray-600 text-sm">
          Cross-referencing OIG LEIE…
        </div>
      )}
      {error != null && (
        <div className="card border-red-900/60">
          <p className="text-sm text-red-400">Failed to load: {String(error)}</p>
        </div>
      )}

      {data && data.total === 0 && (
        <div className="card">
          <p className="text-sm text-gray-500">
            No scanned providers matched the OIG exclusion list.
          </p>
        </div>
      )}

      {data && data.total > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] text-gray-600 uppercase tracking-wider border-b border-gray-800">
                <th className="py-2 pr-4">NPI</th>
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">State</th>
                <th className="py-2 pr-4">Specialty</th>
                <th className="py-2 pr-4">Exclusion Type</th>
                <th className="py-2 pr-4">Excluded Since</th>
                <th className="py-2 pr-4 text-right">Total Paid</th>
                <th className="py-2 text-right">Risk</th>
              </tr>
            </thead>
            <tbody>
              {data.providers.map(p => (
                <tr key={p.npi} className="border-b border-gray-900 hover:bg-gray-900/40" style={{ borderLeft: `3px solid ${threatColor(p.risk_score)}` }}>
                  <td className="py-2 pr-4 font-mono text-xs">
                    <Link to={`/providers/${p.npi}`} className="text-blue-400 hover:underline">{p.npi}</Link>
                  </td>
                  <td className="py-2 pr-4 text-gray-300">{p.provider_name || '—'}<ProviderFlags npi={p.npi} className="ml-1.5" /></td>
                  <td className="py-2 pr-4 text-gray-400">{p.state || '—'}</td>
                  <td className="py-2 pr-4 text-gray-500 text-xs">{p.specialty || '—'}</td>
                  <td className="py-2 pr-4">
                    <span className="text-xs px-2 py-0.5 bg-red-950/60 border border-red-900 rounded text-red-400 font-mono">
                      {p.excl_type || '—'}
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-gray-400 font-mono text-xs">{p.excl_date || '—'}</td>
                  <td className="py-2 pr-4 text-right font-mono text-gray-300">{fmt(p.total_paid)}</td>
                  <td className="py-2 text-right font-mono text-gray-400">{p.risk_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
