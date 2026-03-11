import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { SignalResult } from '../lib/types'
import { fmt } from '../lib/format'

const SIGNAL_LABELS: Record<string, string> = {
  billing_concentration:    'Billing Concentration',
  revenue_per_bene_outlier: 'Revenue Outlier',
  claims_per_bene_anomaly:  'Claims Anomaly',
  billing_ramp_rate:        'Billing Ramp',
  bust_out_pattern:         'Bust-Out Pattern',
  ghost_billing:            'Ghost Billing',
  total_spend_outlier:      'Total Spend Outlier',
  billing_consistency:      'Billing Consistency',
  bene_concentration:       'Beneficiary Concentration',
  upcoding_pattern:         'Upcoding Pattern',
  address_cluster_risk:     'Address Cluster',
  oig_excluded:             'OIG Excluded',
  specialty_mismatch:       'Specialty Mismatch',
  corporate_shell_risk:     'Corporate Shell',
  geographic_impossibility: 'Geographic Impossibility',
  dead_npi_billing:         'Dead NPI Billing',
  new_provider_explosion:   'New Provider Explosion',
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Ev = Record<string, any>

function EvidencePanel({ npi, signal }: { npi: string; signal: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['signal-evidence', npi, signal],
    queryFn: () => api.signalEvidence(npi, signal),
    staleTime: 60_000,
  })

  if (isLoading) return <div className="text-gray-500 text-xs py-3 animate-pulse">Loading evidence...</div>
  if (error || !data) return <div className="text-red-400 text-xs py-2">Failed to load evidence</div>

  const ev = data as Ev
  const methodology: string = ev.methodology ?? ''
  const threshold: string = ev.threshold ?? ''

  return (
    <div className="mt-3 space-y-3 border-t border-gray-700/50 pt-3">
      {/* Methodology */}
      <div>
        <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">How This Was Detected</p>
        <p className="text-xs text-gray-300 leading-relaxed">{methodology}</p>
      </div>

      {/* Threshold */}
      <div>
        <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Detection Threshold</p>
        <p className="text-xs text-yellow-400 font-mono">{threshold}</p>
      </div>

      {/* Signal-specific evidence */}
      {signal === 'billing_concentration' && ev.top_codes && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
            Proof — HCPCS Code Breakdown (total: {fmt(ev.total_billed as number)})
          </p>
          <div className="space-y-1">
            {(ev.top_codes as { code: string; paid: number; pct: number; claims: number }[]).map(c => (
              <div key={c.code} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-white w-14">{c.code}</span>
                <div className="flex-1 bg-gray-800 rounded-full h-3 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${c.pct > 80 ? 'bg-red-500' : c.pct > 50 ? 'bg-yellow-500' : 'bg-blue-500'}`}
                    style={{ width: `${Math.min(c.pct, 100)}%` }}
                  />
                </div>
                <span className="text-gray-400 w-14 text-right">{c.pct}%</span>
                <span className="text-gray-500 w-16 text-right">{fmt(c.paid)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {signal === 'revenue_per_bene_outlier' && ev.z_score != null && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — Statistical Comparison</p>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2">
              <p className="text-gray-500">This Provider</p>
              <p className="text-red-300 font-bold text-lg">{fmt(ev.this_provider as number)}</p>
              <p className="text-gray-500">per beneficiary</p>
            </div>
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2">
              <p className="text-gray-500">Peer Average</p>
              <p className="text-gray-300 font-bold text-lg">{fmt(ev.peer_mean as number)}</p>
              <p className="text-gray-500">per beneficiary</p>
            </div>
          </div>
          <div className="flex gap-4 text-xs mt-2 text-gray-400">
            <span>Z-score: <span className="text-red-400 font-mono font-bold">{(ev.z_score as number).toFixed(1)}σ</span></span>
            {ev.multiple_of_mean && <span>{(ev.multiple_of_mean as number)}x the peer mean</span>}
            <span>Peer std dev: {fmt(ev.peer_std as number)}</span>
          </div>
        </div>
      )}

      {signal === 'claims_per_bene_anomaly' && ev.z_score != null && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — Claims Volume</p>
          <div className="grid grid-cols-3 gap-3 text-xs">
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2 text-center">
              <p className="text-gray-500">Claims/Bene</p>
              <p className="text-red-300 font-bold text-lg">{(ev.this_provider as number).toFixed(1)}</p>
            </div>
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2 text-center">
              <p className="text-gray-500">Peer Mean</p>
              <p className="text-gray-300 font-bold text-lg">{(ev.peer_mean as number).toFixed(1)}</p>
            </div>
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2 text-center">
              <p className="text-gray-500">Z-Score</p>
              <p className="text-red-400 font-bold text-lg">{(ev.z_score as number).toFixed(1)}σ</p>
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            {(ev.total_claims as number).toLocaleString()} total claims across {(ev.total_beneficiaries as number).toLocaleString()} beneficiaries
          </p>
        </div>
      )}

      {signal === 'billing_ramp_rate' && ev.first_6_months && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — First 6 Months</p>
          <div className="flex items-end gap-1 h-20">
            {(ev.first_6_months as { month: string; total_paid: number }[]).map((m, i) => {
              const max = Math.max(...(ev.first_6_months as { total_paid: number }[]).map(x => x.total_paid))
              const h = max > 0 ? (m.total_paid / max) * 100 : 0
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[9px] text-gray-500">{fmt(m.total_paid)}</span>
                  <div className="w-full bg-gray-800 rounded-t relative" style={{ height: `${Math.max(h, 2)}%` }}>
                    <div className={`absolute inset-0 rounded-t ${i === 5 ? 'bg-red-500' : 'bg-blue-500/70'}`} />
                  </div>
                  <span className="text-[9px] text-gray-600">M{i + 1}</span>
                </div>
              )
            })}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Growth: {fmt(ev.month_1_billing as number)} to {fmt(ev.month_6_billing as number)}
            {ev.growth_pct !== 'infinite' ? ` (+${ev.growth_pct}%)` : ' (from $0)'}
          </p>
        </div>
      )}

      {signal === 'bust_out_pattern' && ev.timeline && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — Billing Timeline</p>
          <div className="flex items-end gap-px h-16">
            {(ev.timeline as { month: string; total_paid: number; is_peak: boolean }[]).map((m, i) => {
              const max = Math.max(...(ev.timeline as { total_paid: number }[]).map(x => x.total_paid))
              const h = max > 0 ? (m.total_paid / max) * 100 : 0
              return (
                <div
                  key={i}
                  className={`flex-1 rounded-t ${m.is_peak ? 'bg-red-500' : m.total_paid === 0 ? 'bg-gray-800' : 'bg-blue-500/60'}`}
                  style={{ height: `${Math.max(h, 2)}%` }}
                  title={`${m.month}: ${fmt(m.total_paid)}`}
                />
              )
            })}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Peak: {fmt(ev.peak_amount as number)} in {ev.peak_month as string}, followed by sustained $0 months
          </p>
        </div>
      )}

      {signal === 'ghost_billing' && ev.months && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
            Proof — Beneficiary Counts ({ev.ghost_month_count as number}/{ev.total_months as number} months at exactly 12)
          </p>
          <div className="grid grid-cols-6 gap-1 text-[10px]">
            {(ev.months as { month: string; beneficiaries: number; is_ghost: boolean; total_paid: number }[]).slice(0, 24).map((m, i) => (
              <div
                key={i}
                className={`rounded px-1 py-0.5 text-center ${m.is_ghost ? 'bg-red-950/50 border border-red-800 text-red-300' : 'bg-gray-800 text-gray-500'}`}
              >
                <div className="font-mono">{m.beneficiaries}</div>
                <div className="text-[8px] text-gray-600">{m.month?.slice(-5)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {signal === 'total_spend_outlier' && ev.z_score != null && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — Spend Comparison</p>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2">
              <p className="text-gray-500">This Provider</p>
              <p className="text-red-300 font-bold text-lg">{fmt(ev.this_provider as number)}</p>
            </div>
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2">
              <p className="text-gray-500">Peer Average ({ev.peer_count as number} providers)</p>
              <p className="text-gray-300 font-bold text-lg">{fmt(ev.peer_mean as number)}</p>
            </div>
          </div>
          <div className="flex gap-4 text-xs mt-2 text-gray-400">
            <span>Z-score: <span className="text-red-400 font-mono font-bold">{(ev.z_score as number).toFixed(1)}σ</span></span>
            {ev.multiple_of_mean && <span>{(ev.multiple_of_mean as number)}x the peer mean</span>}
          </div>
        </div>
      )}

      {signal === 'billing_consistency' && ev.monthly_values && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
            Proof — Monthly Values (CV = {(ev.cv as number).toFixed(4)})
          </p>
          <div className="flex items-end gap-px h-16">
            {(ev.monthly_values as { month: string; total_paid: number }[]).map((m, i) => {
              const max = Math.max(...(ev.monthly_values as { total_paid: number }[]).map(x => x.total_paid))
              const h = max > 0 ? (m.total_paid / max) * 100 : 0
              return (
                <div
                  key={i}
                  className="flex-1 bg-yellow-500/60 rounded-t"
                  style={{ height: `${Math.max(h, 2)}%` }}
                  title={`${m.month}: ${fmt(m.total_paid)}`}
                />
              )
            })}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Mean: {fmt(ev.monthly_mean as number)}/month, Std Dev: {fmt(ev.monthly_std as number)}, {ev.active_months as number} active months
          </p>
        </div>
      )}

      {signal === 'bene_concentration' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — Claims vs Beneficiaries</p>
          <div className="grid grid-cols-3 gap-3 text-xs">
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2 text-center">
              <p className="text-gray-500">Claims</p>
              <p className="text-white font-bold text-lg">{(ev.total_claims as number).toLocaleString()}</p>
            </div>
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2 text-center">
              <p className="text-gray-500">Beneficiaries</p>
              <p className="text-white font-bold text-lg">{(ev.total_beneficiaries as number).toLocaleString()}</p>
            </div>
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2 text-center">
              <p className="text-gray-500">Ratio</p>
              <p className="text-red-300 font-bold text-lg">{(ev.claims_per_bene as number).toFixed(1)}</p>
            </div>
          </div>
        </div>
      )}

      {signal === 'upcoding_pattern' && ev.em_families && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — E/M Code Distribution</p>
          {(ev.em_families as { family: string; total_claims: number; codes: { code: string; claims: number; pct: number }[] }[]).map(fam => (
            <div key={fam.family} className="mb-2">
              <p className="text-xs text-gray-400 mb-1">{fam.family} ({fam.total_claims} claims)</p>
              <div className="flex gap-1">
                {fam.codes.map(c => (
                  <div
                    key={c.code}
                    className={`flex-1 rounded p-1 text-center text-[10px] ${c.pct > 50 ? 'bg-red-950/50 border border-red-800 text-red-300' : 'bg-gray-800 text-gray-400'}`}
                  >
                    <div className="font-mono">{c.code}</div>
                    <div className="font-bold">{c.pct}%</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {signal === 'address_cluster_risk' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
            Proof — {ev.cluster_size as number} Providers at This Address
          </p>
          {ev.address && (
            <p className="text-xs text-gray-300 mb-2 font-mono">
              {(ev.address as { line1: string; city: string; state: string; zip: string }).line1}, {(ev.address as { line1: string; city: string; state: string; zip: string }).city}, {(ev.address as { line1: string; city: string; state: string; zip: string }).state} {(ev.address as { line1: string; city: string; state: string; zip: string }).zip}
            </p>
          )}
          {(ev.co_located_providers as { npi: string; name: string; risk_score: number; total_paid: number }[])?.length > 0 && (
            <div className="space-y-1">
              {(ev.co_located_providers as { npi: string; name: string; risk_score: number; total_paid: number }[]).map(p => (
                <div key={p.npi} className="flex items-center gap-2 text-xs bg-gray-800/50 rounded px-2 py-1">
                  <span className="font-mono text-blue-400">{p.npi}</span>
                  <span className="text-gray-300 flex-1 truncate">{p.name}</span>
                  <span className={`font-mono ${p.risk_score >= 50 ? 'text-red-400' : 'text-gray-500'}`}>
                    risk {p.risk_score}
                  </span>
                  <span className="text-gray-500">{fmt(p.total_paid)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {signal === 'specialty_mismatch' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
            Proof — {ev.specialty as string} (keyword: {ev.matched_keyword as string})
          </p>
          <div className="grid grid-cols-2 gap-3 text-xs mb-2">
            <div className="bg-green-950/30 border border-green-900/50 rounded p-2">
              <p className="text-gray-500 mb-1">Within Specialty ({ev.inside_pct as number}%)</p>
              {(ev.inside_specialty_codes as { code: string; paid: number }[])?.length > 0 ? (
                <div className="space-y-0.5">
                  {(ev.inside_specialty_codes as { code: string; paid: number }[]).slice(0, 5).map(c => (
                    <div key={c.code} className="flex justify-between">
                      <span className="font-mono text-green-400">{c.code}</span>
                      <span className="text-gray-400">{fmt(c.paid)}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="text-gray-600 italic">None</p>}
            </div>
            <div className="bg-red-950/30 border border-red-900/50 rounded p-2">
              <p className="text-gray-500 mb-1">Outside Specialty ({ev.outside_pct as number}%)</p>
              {(ev.outside_specialty_codes as { code: string; paid: number }[])?.length > 0 ? (
                <div className="space-y-0.5">
                  {(ev.outside_specialty_codes as { code: string; paid: number }[]).slice(0, 5).map(c => (
                    <div key={c.code} className="flex justify-between">
                      <span className="font-mono text-red-400">{c.code}</span>
                      <span className="text-gray-400">{fmt(c.paid)}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="text-gray-600 italic">None</p>}
            </div>
          </div>
          {ev.valid_prefixes && (
            <p className="text-[10px] text-gray-600">
              Expected code prefixes: {(ev.valid_prefixes as string[]).join(', ')}
            </p>
          )}
        </div>
      )}

      {signal === 'corporate_shell_risk' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
            Proof — {ev.cluster_size as number} NPIs Under Same Official
          </p>
          {ev.authorized_official && (
            <p className="text-xs text-gray-300 mb-2">
              Official: <span className="text-white font-medium">{(ev.authorized_official as { name: string; title: string }).name}</span>
              {(ev.authorized_official as { name: string; title: string }).title && (
                <span className="text-gray-500"> ({(ev.authorized_official as { name: string; title: string }).title})</span>
              )}
            </p>
          )}
          {(ev.sibling_npis as { npi: string; name: string; risk_score: number; total_paid: number }[])?.length > 0 && (
            <div className="space-y-1">
              {(ev.sibling_npis as { npi: string; name: string; risk_score: number; total_paid: number }[]).map(p => (
                <div key={p.npi} className="flex items-center gap-2 text-xs bg-gray-800/50 rounded px-2 py-1">
                  <span className="font-mono text-blue-400">{p.npi}</span>
                  <span className="text-gray-300 flex-1 truncate">{p.name}</span>
                  <span className={`font-mono ${p.risk_score >= 50 ? 'text-red-400' : 'text-gray-500'}`}>
                    risk {p.risk_score}
                  </span>
                  <span className="text-gray-500">{fmt(p.total_paid)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {signal === 'geographic_impossibility' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — State Mismatch</p>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2 text-center">
              <p className="text-gray-500">NPPES Registration</p>
              <p className="text-white font-bold text-xl">{ev.nppes_state as string}</p>
            </div>
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2 text-center">
              <p className="text-gray-500">Billing State</p>
              <p className="text-red-300 font-bold text-xl">{ev.billing_state as string}</p>
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Adjacent states to {ev.nppes_state as string}: {(ev.adjacent_states as string[])?.join(', ') || 'None'}
            {ev.is_adjacent === false && <span className="text-red-400 ml-2">NOT ADJACENT</span>}
          </p>
        </div>
      )}

      {signal === 'oig_excluded' && ev.record && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — OIG LEIE Record</p>
          <div className="bg-red-950/40 border border-red-900/50 rounded p-2 text-xs space-y-1">
            {Object.entries(ev.record as Record<string, string>).map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <span className="text-gray-500 uppercase w-24 shrink-0">{k}:</span>
                <span className="text-red-300">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {signal === 'dead_npi_billing' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — NPI Status</p>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2">
              <p className="text-gray-500">NPI Status</p>
              <p className="text-red-300 font-bold uppercase">{ev.npi_status as string}</p>
              {ev.deactivation_date && <p className="text-gray-500 mt-1">Deactivated: {ev.deactivation_date as string}</p>}
            </div>
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2">
              <p className="text-gray-500">Billing Activity</p>
              <p className="text-white font-bold">{fmt(ev.total_paid as number)}</p>
              <p className="text-gray-500">{(ev.total_claims as number).toLocaleString()} claims</p>
            </div>
          </div>
        </div>
      )}

      {signal === 'new_provider_explosion' && (
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Proof — Provider Age vs Billing</p>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-gray-800/50 border border-gray-700/50 rounded p-2">
              <p className="text-gray-500">NPI Enumerated</p>
              <p className="text-white font-bold">{ev.enumeration_date as string}</p>
              {ev.age_months != null && <p className="text-gray-500">{(ev.age_months as number).toFixed(0)} months ago</p>}
            </div>
            <div className="bg-red-950/40 border border-red-900/50 rounded p-2">
              <p className="text-gray-500">Total Billing</p>
              <p className="text-red-300 font-bold">{fmt(ev.total_paid as number)}</p>
            </div>
          </div>
        </div>
      )}

      <p className="text-[10px] text-gray-600 italic border-t border-gray-800 pt-2">
        Source: OIG Medicaid Fraud Control Units methodology, CMS Fraud Prevention System, 42 CFR Part 455
      </p>
    </div>
  )
}

interface Props {
  signals: SignalResult[]
  npi?: string
}

export default function FraudFlagsTable({ signals, npi }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const active = signals.filter(s => s.flagged)
  const inactive = signals.filter(s => !s.flagged)

  const toggle = (signal: string) => {
    if (!npi) return
    setExpanded(prev => prev === signal ? null : signal)
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500 mb-3">
        <span className={active.length > 0 ? 'text-red-400 font-semibold' : 'text-green-400 font-semibold'}>
          {active.length}
        </span> of {signals.length} signals triggered
        {npi && <span className="text-gray-600 ml-2">(click a flag to see evidence)</span>}
      </p>
      {active.map(s => (
        <div
          key={s.signal}
          className={`bg-red-950/30 border border-red-900/50 rounded-lg p-3 border-l-2 border-l-red-500 ${npi ? 'cursor-pointer hover:bg-red-950/50 transition-colors' : ''}`}
          onClick={() => toggle(s.signal)}
        >
          <div className="flex items-start gap-3">
            <span className="text-red-400 text-lg mt-0.5">⚑</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-red-300 font-medium text-sm">{SIGNAL_LABELS[s.signal] ?? s.signal}</span>
                <span className="text-xs text-gray-500">weight {s.weight}</span>
                <span className="ml-auto text-xs font-mono text-red-400">+{(s.score * s.weight).toFixed(1)} pts</span>
                {npi && (
                  <span className="text-gray-600 text-xs">{expanded === s.signal ? '▾' : '▸'}</span>
                )}
              </div>
              <p className="text-gray-400 text-xs mt-0.5">{s.reason}</p>
            </div>
          </div>
          {expanded === s.signal && npi && (
            <EvidencePanel npi={npi} signal={s.signal} />
          )}
        </div>
      ))}
      {inactive.map(s => (
        <div
          key={s.signal}
          className={`bg-gray-900 border border-gray-800 rounded-lg p-3 opacity-50 ${npi ? 'cursor-pointer hover:opacity-70 transition-opacity' : ''}`}
          onClick={() => toggle(s.signal)}
        >
          <div className="flex items-start gap-3">
            <span className="text-gray-600 text-lg mt-0.5">✓</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-gray-500 text-sm">{SIGNAL_LABELS[s.signal] ?? s.signal}</span>
                {npi && (
                  <span className="text-gray-700 text-xs ml-auto">{expanded === s.signal ? '▾' : '▸'}</span>
                )}
              </div>
              <p className="text-gray-600 text-xs mt-0.5">{s.reason}</p>
            </div>
          </div>
          {expanded === s.signal && npi && (
            <EvidencePanel npi={npi} signal={s.signal} />
          )}
        </div>
      ))}
    </div>
  )
}
