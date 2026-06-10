import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { ExclamationTriangleIcon } from './icons'

const BH_PREFIXES = ['Bene_CC_BH']
const TOP_N = 10


function ConditionBar({ label, pct, isBH }: { label: string; pct: number; isBH: boolean }) {
  const width = Math.min(pct, 100)
  const barColor = isBH ? 'bg-purple-500' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="w-44 truncate text-gray-300" title={label}>{label}</div>
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full ${barColor} rounded-full transition-all`} style={{ width: `${width}%` }} />
      </div>
      <div className="w-12 text-right font-mono text-gray-400">{pct.toFixed(1)}%</div>
    </div>
  )
}


export default function DiagnosisMixCard({ npi }: { npi: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['diagnoses', npi],
    queryFn: () => api.providerDiagnoses(npi),
    staleTime: 1000 * 60 * 60, // MUP data updates yearly
  })

  if (isLoading) {
    return (
      <div className="card">
        <h2 className="text-base font-semibold text-gray-300 mb-3">Diagnosis Mix</h2>
        <div className="h-40 flex items-center justify-center text-gray-600 text-sm">Loading…</div>
      </div>
    )
  }

  if (!data) return null

  if (!data.has_data) {
    return (
      <div className="card">
        <div className="flex items-baseline justify-between mb-2">
          <h2 className="text-base font-semibold text-gray-300">Diagnosis Mix</h2>
          <span className="text-xs text-gray-600">CMS MUP-by-Provider</span>
        </div>
        <p className="text-xs text-gray-500">
          {data.message ?? 'No Medicare diagnosis data available for this NPI.'}
        </p>
      </div>
    )
  }

  const mix = data.diagnosis_mix ?? []
  const topMix = mix.slice(0, TOP_N)
  const mismatch = data.mismatch_signal

  return (
    <div className="card space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-300">Diagnosis Mix</h2>
          <p className="text-xs text-gray-600 mt-0.5">
            {data.provider_type ?? ''} · {data.tot_benes?.toLocaleString() ?? '—'} Medicare beneficiaries
            {data.bene_avg_age != null && ` · avg age ${data.bene_avg_age.toFixed(0)}`}
            {data.bene_avg_risk_score != null && ` · HCC risk ${data.bene_avg_risk_score.toFixed(2)}`}
          </p>
        </div>
        <span className="text-xs text-gray-600">{data.data_source ?? 'CMS MUP'}</span>
      </div>

      {mismatch?.flagged && (
        <div className="rounded-md border border-red-800 bg-red-950/30 px-3 py-2">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-red-400 font-semibold text-xs flex items-center gap-1.5"><ExclamationTriangleIcon className="w-3.5 h-3.5" /> DIAGNOSIS-PROCEDURE MISMATCH</span>
            <span className="text-xs text-red-300/80 font-mono">
              score {(mismatch.score * 100).toFixed(0)} · weight {mismatch.weight}
            </span>
          </div>
          <p className="text-xs text-red-200/90">{mismatch.reason}</p>
        </div>
      )}

      {mismatch && !mismatch.flagged && (
        <p className="text-xs text-green-500/80">
          ✓ Top procedures match the Medicare diagnosis denominator.
        </p>
      )}

      {topMix.length > 0 ? (
        <div className="space-y-1.5">
          {topMix.map(d => (
            <ConditionBar
              key={d.column}
              label={d.label}
              pct={d.pct}
              isBH={BH_PREFIXES.some(p => d.column.startsWith(p))}
            />
          ))}
          {mix.length > TOP_N && (
            <p className="text-xs text-gray-600 pt-1">
              + {mix.length - TOP_N} more conditions below {topMix[topMix.length - 1].pct.toFixed(1)}%
            </p>
          )}
        </div>
      ) : (
        <p className="text-xs text-gray-500">No chronic-condition prevalence reported.</p>
      )}
    </div>
  )
}
