import type { SignalResult } from '../lib/types'

const SIGNAL_LABELS: Record<string, string> = {
  billing_concentration:    'Billing Concentration',
  revenue_per_bene_outlier: 'Revenue Outlier',
  claims_per_bene_anomaly:  'Claims Anomaly',
  billing_ramp_rate:        'Billing Ramp',
  bust_out_pattern:         'Bust-Out Pattern',
  ghost_billing:            'Ghost Billing',
  total_spend_outlier:      'Total Spend Outlier',
  billing_consistency:      'Billing Consistency',
}

interface Props {
  signals: SignalResult[]
}

export default function FraudFlagsTable({ signals }: Props) {
  const active = signals.filter(s => s.flagged)
  const inactive = signals.filter(s => !s.flagged)

  return (
    <div className="space-y-2">
      {active.map(s => (
        <div key={s.signal} className="flex items-start gap-3 bg-red-950/30 border border-red-900/50 rounded-lg p-3">
          <span className="text-red-400 text-lg mt-0.5">⚑</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-red-300 font-medium text-sm">{SIGNAL_LABELS[s.signal] ?? s.signal}</span>
              <span className="text-xs text-gray-500">weight {s.weight}</span>
              <span className="ml-auto text-xs font-mono text-red-400">+{(s.score * s.weight).toFixed(1)} pts</span>
            </div>
            <p className="text-gray-400 text-xs mt-0.5">{s.reason}</p>
          </div>
        </div>
      ))}
      {inactive.map(s => (
        <div key={s.signal} className="flex items-start gap-3 bg-gray-900 border border-gray-800 rounded-lg p-3 opacity-50">
          <span className="text-gray-600 text-lg mt-0.5">✓</span>
          <div>
            <span className="text-gray-500 text-sm">{SIGNAL_LABELS[s.signal] ?? s.signal}</span>
            <p className="text-gray-600 text-xs mt-0.5">{s.reason}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
