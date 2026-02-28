import { useState } from 'react'

const SIGNALS = [
  {
    name: 'Billing Concentration',
    weight: 15,
    description:
      'Flags when a single procedure code makes up more than 80% of total billing. Legitimate providers serving broad patient needs bill a mix of codes. Single-code dominance is a top OIG enforcement target, especially for personal care, home health, and DME providers.',
    flag: '>80% of revenue from one HCPCS code',
    source: 'OIG concentration analysis',
  },
  {
    name: 'Revenue Outlier',
    weight: 20,
    description:
      'Compares revenue-per-beneficiary against providers billing the same top procedure code (same-service peer group). Flags if more than 3 standard deviations above the peer average — the threshold used in CMS Comparative Billing Reports.',
    flag: 'Revenue/beneficiary >3σ above same-code peer mean',
    source: 'CMS Comparative Billing Reports / OIG statistical method',
  },
  {
    name: 'Claims Anomaly',
    weight: 15,
    description:
      'Compares total claims per unique beneficiary against other providers billing the same top procedure code — so home health agencies are compared to home health agencies, not to specialists. OIG cases have documented 312 claims per beneficiary in a single year. The threshold self-calibrates to the peer group.',
    flag: 'Claims/beneficiary >3σ above same-code peer mean',
    source: 'OIG enforcement case patterns',
  },
  {
    name: 'Billing Ramp',
    weight: 15,
    description:
      'Flags explosive billing growth in the first 6 months, requiring both a large percentage increase AND at least $50K in month-6 billing. OIG screens new providers (especially home health and DME) for rapid ramp-up before investigators can respond.',
    flag: '>400% growth in first 6 months with ≥$50K month-6 billing',
    source: 'OIG new-provider enrollment screening',
  },
  {
    name: 'Bust-Out Pattern',
    weight: 15,
    description:
      'A peak billing period followed by 3+ consecutive months of $0 claims — the "ramp and exit" signature found repeatedly in OIG enforcement actions. Fraudulent providers (DME, home health, personal care) bill aggressively then abruptly stop.',
    flag: 'Billing peak + ≥3 months of zero activity',
    source: 'OIG enforcement action pattern analysis',
  },
  {
    name: 'Ghost Billing',
    weight: 5,
    description:
      'CMS suppresses exact beneficiary counts below 11, always displaying 12 for privacy. Providers consistently showing exactly 12 beneficiaries across many billing months may be fabricating claims designed to stay below the detection floor.',
    flag: '>50% of billing months show exactly 12 beneficiaries',
    source: 'CMS data suppression rule / OIG phantom billing investigations',
  },
  {
    name: 'Total Spend Outlier',
    weight: 10,
    description:
      'Compares this provider\'s total Medicaid payments against all scanned providers using a z-score. Absolute spending level is the single strongest predictor in OIG machine learning models — major fraud cases almost universally involve providers billing far above the peer median.',
    flag: 'Total payments >3σ above peer mean',
    source: 'OIG ML model — strongest single predictor',
  },
  {
    name: 'Billing Consistency',
    weight: 5,
    description:
      'Real providers have natural month-to-month billing variation from patient mix, seasonality, and service delivery. A coefficient of variation below 0.15 across 12+ months is an OIG-documented red flag for automated or manufactured claims — billing that looks computer-generated.',
    flag: 'Monthly billing CV < 0.15 over 12+ months',
    source: 'OIG automated-claims detection methodology',
  },
]

export default function RiskScoreModal() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-bold text-gray-500 border border-gray-700 hover:border-gray-500 hover:text-gray-300 transition-colors ml-1 leading-none"
        title="What does the risk score mean?"
      >
        ?
      </button>

      {open && (
        <div
          className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
          onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}
        >
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b border-gray-800">
              <div>
                <h2 className="text-white font-bold text-lg">Risk Score Explained</h2>
                <p className="text-gray-400 text-sm mt-0.5">
                  How the fraud risk score (0–100) is calculated
                </p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2"
              >
                ✕
              </button>
            </div>

            <div className="p-5 space-y-5">
              {/* Score bands */}
              <div className="grid grid-cols-3 gap-3 text-center text-xs">
                <div className="bg-yellow-900/30 border border-yellow-800/50 rounded-lg p-3">
                  <div className="text-yellow-400 font-bold text-xl">0–49</div>
                  <div className="text-yellow-300 font-medium mt-0.5">Low Risk</div>
                  <div className="text-gray-500 mt-1">Normal billing patterns</div>
                </div>
                <div className="bg-orange-900/30 border border-orange-800/50 rounded-lg p-3">
                  <div className="text-orange-400 font-bold text-xl">50–74</div>
                  <div className="text-orange-300 font-medium mt-0.5">Medium Risk</div>
                  <div className="text-gray-500 mt-1">Some anomalies detected</div>
                </div>
                <div className="bg-red-900/30 border border-red-800/50 rounded-lg p-3">
                  <div className="text-red-400 font-bold text-xl">75–100</div>
                  <div className="text-red-300 font-medium mt-0.5">High Risk</div>
                  <div className="text-gray-500 mt-1">Multiple flags triggered</div>
                </div>
              </div>

              {/* Formula */}
              <div className="bg-gray-800/60 rounded-lg p-4 text-xs space-y-1.5">
                <p>
                  <span className="text-gray-200 font-semibold">Formula: </span>
                  <span className="text-gray-400">Risk Score = Σ (signal_score × weight) across all 6 signals</span>
                </p>
                <p>
                  <span className="text-gray-200 font-semibold">Signal score: </span>
                  <span className="text-gray-400">0.0 to 1.0 per signal, multiplied by its weight before summing. Max possible = 100.</span>
                </p>
                <p>
                  <span className="text-gray-200 font-semibold">Review threshold: </span>
                  <span className="text-gray-400">Providers with a score ≥ 10 are added to the Review Queue for investigation.</span>
                </p>
              </div>

              {/* Signal breakdown */}
              <div className="space-y-3">
                <h3 className="text-gray-300 font-semibold text-sm">The 6 Fraud Signals</h3>
                {SIGNALS.map(sig => (
                  <div key={sig.name} className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-white font-medium text-sm">{sig.name}</span>
                      <span className="text-xs px-1.5 py-0.5 bg-blue-900/60 text-blue-400 rounded font-mono">
                        weight {sig.weight}
                      </span>
                    </div>
                    <p className="text-gray-400 text-xs leading-relaxed">{sig.description}</p>
                    <p className="text-xs mt-1.5">
                      <span className="text-gray-600">Flagged when: </span>
                      <span className="text-red-400/90">{sig.flag}</span>
                    </p>
                    <p className="text-xs mt-0.5 text-gray-600 italic">Source: {sig.source}</p>
                  </div>
                ))}
              </div>

              <p className="text-gray-600 text-xs border-t border-gray-800 pt-4">
                Risk scores are derived from Medicaid billing data and statistical analysis only.
                They do not constitute a legal determination of fraud and should be used as a
                triage tool for further investigation.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
