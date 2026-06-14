import { useState } from 'react'

/**
 * "How to bring in new data" runbook popup for the Scan & Data page.
 * Documents the refresh cadence + the exact workstation steps (the precompute /
 * backfill / GCS-upload pipeline the web UI can't trigger). Kept in one place
 * so the operator never has to remember the order.
 */

const CADENCE: { source: string; cadence: string; how: string }[] = [
  { source: 'Medicaid Provider Spending (core 2.74 GB parquet)', cadence: 'Quarterly / when HHS republishes', how: 'This page → Data Source → Check for update → Update now, then re-scan' },
  { source: 'NPPES (taxonomy, authorized officials, deactivations)', cadence: 'Monthly', how: 'Workstation runbook steps 1–5 below' },
  { source: 'OIG LEIE exclusions', cadence: 'Monthly', how: 'Automatic — downloaded at backend startup' },
  { source: 'SAM.gov exclusions', cadence: 'Live', how: 'Automatic — queried per provider via API' },
  { source: 'CMS Open Payments', cadence: 'Annual (June)', how: 'Automatic — queried per provider via API' },
  { source: 'CMS MUP (Medicare diagnosis proxy)', cadence: 'When CMS releases (~annual)', how: 'This page → MUP diagnosis cache → Refresh' },
]

const STEPS: { cmd: string; note: string }[] = [
  { cmd: '# 1. Download the latest monthly NPPES bulk zip to G:\\temp\\, then extract it (the\n#    backfill script reuses G:/temp/nppes_extract).', note: 'NPPES "NPI Files" → full monthly replacement. ~1 GB zip → ~10 GB CSV.' },
  { cmd: 'G:\\Python311\\python.exe -X utf8 backend\\scripts\\backfill_nppes_bulk.py', note: 'Merges taxonomy + authorized officials + entity type into the full + slim caches.' },
  { cmd: 'G:\\Python311\\python.exe -X utf8 backend\\scripts\\build_deactivations.py', note: 'Rebuilds the deactivated-NPI lookup (powers dead_npi_billing).' },
  { cmd: 'G:\\Python311\\python.exe -X utf8 backend\\scripts\\precompute_analyses.py', note: 'Claim patterns, ownership networks, hcpcs_index.parquet, billing trends, slim backfill.' },
  { cmd: 'gcloud storage cp -Z backend\\prescan_slim.json backend\\precomputed_analyses.json backend\\npi_deactivations.json gs://medicaid-inspector-data/\ngcloud storage cp backend\\hcpcs_index.parquet gs://medicaid-inspector-data/', note: 'Upload artifacts (-Z gzip for JSON; parquet is already compressed). Run from the repo root.' },
  { cmd: 'gcloud run deploy medicaid-inspector-api --source . --project medicaid-inspector --region us-central1 --quiet', note: 'Bounce Cloud Run so it reloads the new artifacts at startup. (Set $env:TMP=G:\\temp first.)' },
]

export default function DataRefreshGuide() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="px-3 py-1.5 text-xs font-mono uppercase tracking-wider bg-surface-2 hover:bg-hairline border border-hairline hover:border-filament-dim rounded text-filament-core transition-colors label-stamp"
        title="Cadence + step-by-step runbook for refreshing the data"
      >
        How to refresh data
      </button>

      {open && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-void/80 p-4" onClick={() => setOpen(false)}>
          <div className="bg-surface-1 border border-hairline rounded-xl w-full max-w-3xl max-h-[88vh] flex flex-col shadow-glow-filament" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-hairline">
              <h3 className="font-display font-semibold text-ink-primary">Bringing in new data — cadence & runbook</h3>
              <button onClick={() => setOpen(false)} className="text-ink-tertiary hover:text-ink-primary text-lg leading-none">×</button>
            </div>

            <div className="overflow-auto px-5 py-4 space-y-5">
              <section>
                <h4 className="text-[11px] uppercase tracking-[0.14em] text-ink-tertiary label-stamp mb-2">Recommended cadence</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-ink-tertiary border-b border-hairline">
                        <th className="py-1.5 pr-3">Source</th><th className="py-1.5 pr-3">Refresh</th><th className="py-1.5">How</th>
                      </tr>
                    </thead>
                    <tbody>
                      {CADENCE.map((c) => (
                        <tr key={c.source} className="border-b border-hairline/50 align-top">
                          <td className="py-1.5 pr-3 text-ink-secondary">{c.source}</td>
                          <td className="py-1.5 pr-3 text-filament-core whitespace-nowrap font-mono">{c.cadence}</td>
                          <td className="py-1.5 text-ink-tertiary">{c.how}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-ink-tertiary mt-2">
                  Quick rule of thumb: <span className="text-ink-secondary">monthly</span> NPPES + deactivation refresh (steps below);
                  re-scan the core dataset <span className="text-ink-secondary">quarterly</span> or whenever “Check for update” shows a newer file.
                </p>
              </section>

              <section>
                <h4 className="text-[11px] uppercase tracking-[0.14em] text-ink-tertiary label-stamp mb-2">Automatic — no action needed</h4>
                <p className="text-xs text-ink-tertiary">OIG LEIE (downloaded at backend startup), SAM.gov and CMS Open Payments (live per-provider API). These are always current.</p>
              </section>

              <section>
                <h4 className="text-[11px] uppercase tracking-[0.14em] text-ink-tertiary label-stamp mb-2">Manual runbook (workstation) — run in order</h4>
                <ol className="space-y-3">
                  {STEPS.map((s, i) => (
                    <li key={i} className="text-xs">
                      <div className="flex items-start gap-2">
                        <span className="font-mono text-filament-dim shrink-0">{i + 1}.</span>
                        <div className="flex-1 min-w-0">
                          <pre className="bg-surface-0 border border-hairline rounded px-3 py-2 text-[11px] font-mono text-ink-secondary whitespace-pre-wrap break-words">{s.cmd}</pre>
                          <p className="text-ink-tertiary mt-1">{s.note}</p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
                <p className="text-[11px] text-ink-tertiary mt-3 border-l-2 border-filament-dim pl-3">
                  Use the <span className="font-mono text-ink-secondary">G:\Python311</span> interpreter (it has duckdb). If C: is full,
                  set <span className="font-mono text-ink-secondary">$env:TMP=&quot;G:\temp&quot;</span> before deploying. After the deploy, open the
                  Fraud Brain and hit Recompute to confirm the new data took.
                </p>
              </section>
            </div>

            <div className="px-5 py-3 border-t border-hairline flex justify-end">
              <button onClick={() => setOpen(false)} className="px-3 py-1.5 text-xs font-medium bg-filament-core text-void rounded hover:bg-filament-core/90 transition-colors">Got it</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
