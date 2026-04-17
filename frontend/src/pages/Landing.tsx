import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mutate } from '../lib/api'

const PLANS = [
  {
    name: 'Starter',
    price: '$49',
    period: '/month',
    description: 'For individual investigators and small compliance teams',
    features: [
      'Up to 5,000 provider scans/month',
      '8 core fraud signals',
      'Basic risk scoring',
      'CSV export',
      'Email support',
    ],
    cta: 'Start Free Trial',
    highlight: false,
    priceId: 'starter',
  },
  {
    name: 'Professional',
    price: '$199',
    period: '/month',
    description: 'For compliance departments and state Medicaid agencies',
    features: [
      'Unlimited provider scans',
      'All 17 fraud signals',
      'Advanced peer comparison',
      'OIG & SAM.gov exclusion checks',
      'Network analysis & clustering',
      'Review queue & case management',
      'PDF/HTML report generation',
      'Priority support',
    ],
    cta: 'Start Free Trial',
    highlight: true,
    priceId: 'professional',
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    description: 'For large agencies, MCOs, and federal oversight bodies',
    features: [
      'Everything in Professional',
      'Multi-state scanning',
      'Custom fraud signal development',
      'API access & webhooks',
      'SSO / SAML integration',
      'Dedicated account manager',
      'On-premise deployment option',
      'SLA & BAA available',
    ],
    cta: 'Contact Sales',
    highlight: false,
    priceId: 'enterprise',
  },
]

const FEATURES = [
  {
    icon: (
      <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
      </svg>
    ),
    title: '17 Fraud Signals',
    desc: 'Detect billing concentration, bust-out patterns, ghost billing, upcoding, and 13 more OIG-based fraud indicators.',
  },
  {
    icon: (
      <svg className="w-8 h-8 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
      </svg>
    ),
    title: 'Real-Time Scanning',
    desc: 'Scan 100K+ Medicaid providers against CMS/HHS Parquet datasets with live progress tracking.',
  },
  {
    icon: (
      <svg className="w-8 h-8 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
      </svg>
    ),
    title: 'Exclusion Screening',
    desc: 'Cross-reference against OIG LEIE, SAM.gov federal exclusion lists, and CMS Open Payments.',
  },
  {
    icon: (
      <svg className="w-8 h-8 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" />
      </svg>
    ),
    title: 'Interactive Dashboard',
    desc: 'State heatmaps, network graphs, anomaly drill-downs, and per-provider risk profiles.',
  },
  {
    icon: (
      <svg className="w-8 h-8 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
      </svg>
    ),
    title: 'Case Management',
    desc: 'Review queue with status tracking, assignment, audit trails, and bulk actions for your team.',
  },
  {
    icon: (
      <svg className="w-8 h-8 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
      </svg>
    ),
    title: 'Report Generation',
    desc: 'Export comprehensive provider reports with HCPCS breakdowns, timelines, and fraud signal analysis.',
  },
]

const STATS = [
  { value: '106K+', label: 'Providers Scanned' },
  { value: '17', label: 'Fraud Signals' },
  { value: '38K+', label: 'Providers Flagged' },
  { value: '$1.2T', label: 'Medicaid Spend Analyzed' },
]

interface Props {
  onLogin: () => void
}

export default function Landing({ onLogin }: Props) {
  const [email, setEmail] = useState('')
  const navigate = useNavigate()

  const handleCheckout = async (priceId: string) => {
    if (priceId === 'enterprise') {
      window.location.href = 'mailto:sales@medicaidinspector.com?subject=Enterprise%20Inquiry'
      return
    }
    try {
      const data = await mutate<{ url?: string }>('POST', '/billing/create-checkout', { plan: priceId, email })
      if (data.url) {
        // Validate the redirect target before navigating. Stripe checkout URLs
        // are always https://checkout.stripe.com/* or https://*.stripe.com/*
        // — anything else (http://, javascript:, data:, attacker-controlled
        // domain) must be refused to prevent open-redirect / phishing.
        let parsed: URL | null = null
        try {
          parsed = new URL(data.url)
        } catch {
          parsed = null
        }
        const isSafe =
          parsed !== null &&
          parsed.protocol === 'https:' &&
          (parsed.hostname === 'checkout.stripe.com' ||
            parsed.hostname.endsWith('.stripe.com'))
        if (isSafe) {
          window.location.href = parsed!.toString()
        } else {
          // Refuse to follow an unexpected redirect target.
          console.error('Refusing to follow unsafe checkout URL:', data.url)
          onLogin()
        }
      }
    } catch {
      // Stripe not configured — go to login
      onLogin()
    }
  }

  return (
    <div className="min-h-screen">
      {/* Nav */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-gray-950/80 backdrop-blur-md border-b border-gray-800/50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" className="w-8 h-8 shrink-0">
              <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
              <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" strokeWidth="1.5"/>
              <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" strokeWidth="4"/>
              <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
              <text x="28" y="33" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="11" fill="#f59e0b">$</text>
              <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" strokeWidth="4.5" strokeLinecap="round"/>
              <circle cx="46" cy="18" r="6" fill="#ef4444"/>
              <text x="46" y="22" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="9" fill="white">!</text>
            </svg>
            <span className="font-bold text-white text-lg tracking-wide">Medicaid Inspector</span>
          </div>
          <nav className="hidden md:flex items-center gap-6">
            <a href="#features" className="text-sm text-gray-400 hover:text-white transition-colors">Features</a>
            <a href="#pricing" className="text-sm text-gray-400 hover:text-white transition-colors">Pricing</a>
            <button onClick={onLogin} className="text-sm text-gray-400 hover:text-white transition-colors">
              Log In
            </button>
            <button onClick={onLogin} className="btn-primary text-sm">
              Get Started
            </button>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 mb-6 bg-red-950/50 border border-red-800/50 rounded-full">
            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            <span className="text-xs text-red-400 font-medium uppercase tracking-wider">Fraud Detection Platform</span>
          </div>
          <h1 className="text-5xl md:text-6xl font-black text-white leading-tight mb-6">
            Detect Medicaid Fraud<br />
            <span className="bg-gradient-to-r from-blue-400 via-blue-500 to-purple-500 bg-clip-text text-transparent">
              Before It Costs Billions
            </span>
          </h1>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Scan over 100,000 Medicaid providers against 17 OIG-based fraud signals.
            Real-time risk scoring, network analysis, and case management —
            powered by CMS/HHS open data.
          </p>
          <div className="flex items-center justify-center gap-4 mb-16">
            <button onClick={onLogin} className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-3.5 rounded-xl text-base font-semibold transition-all hover:shadow-lg hover:shadow-blue-600/25">
              Start Free Trial
            </button>
            <a href="#features" className="text-gray-400 hover:text-white px-6 py-3.5 rounded-xl text-base font-medium border border-gray-700 hover:border-gray-500 transition-all">
              See How It Works
            </a>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 max-w-3xl mx-auto">
            {STATS.map(s => (
              <div key={s.label} className="text-center">
                <p className="text-3xl font-black text-white">{s.value}</p>
                <p className="text-xs text-gray-500 mt-1 uppercase tracking-wider">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Dashboard Preview */}
      <section className="px-6 pb-20">
        <div className="max-w-5xl mx-auto">
          <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-1 shadow-2xl shadow-black/50">
            <div className="rounded-xl bg-gray-950 border border-gray-800 p-6">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-3 h-3 rounded-full bg-red-500" />
                <div className="w-3 h-3 rounded-full bg-yellow-500" />
                <div className="w-3 h-3 rounded-full bg-green-500" />
                <span className="ml-3 text-xs text-gray-600 font-mono">medicaid-inspector / overview</span>
              </div>
              <div className="grid grid-cols-4 gap-3 mb-4">
                {[
                  { label: 'Providers Scanned', value: '106,660', color: 'text-blue-400' },
                  { label: 'Flagged for Review', value: '38,875', color: 'text-red-400' },
                  { label: 'Avg Risk Score', value: '12.4', color: 'text-yellow-400' },
                  { label: 'Active Signals', value: '17 / 17', color: 'text-green-400' },
                ].map(m => (
                  <div key={m.label} className="bg-gray-900 rounded-lg p-3 border border-gray-800">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">{m.label}</p>
                    <p className={`text-xl font-bold mt-1 ${m.color}`}>{m.value}</p>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-900 rounded-lg p-4 border border-gray-800 h-32 flex items-center justify-center">
                  <p className="text-xs text-gray-600">State Heatmap</p>
                </div>
                <div className="bg-gray-900 rounded-lg p-4 border border-gray-800 h-32 flex items-center justify-center">
                  <p className="text-xs text-gray-600">Fraud Signal Distribution</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-white mb-3">Built for Fraud Investigators</h2>
            <p className="text-gray-400 max-w-xl mx-auto">
              Every feature designed around real OIG enforcement patterns and Medicaid compliance workflows.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {FEATURES.map(f => (
              <div key={f.title} className="card card-glow">
                <div className="mb-4">{f.icon}</div>
                <h3 className="text-white font-semibold mb-2">{f.title}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-white mb-3">Simple, Transparent Pricing</h2>
            <p className="text-gray-400 max-w-xl mx-auto">
              Start with a 14-day free trial. No credit card required.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-6 max-w-5xl mx-auto">
            {PLANS.map(plan => (
              <div
                key={plan.name}
                className={`rounded-xl p-6 border flex flex-col ${
                  plan.highlight
                    ? 'bg-blue-950/30 border-blue-700 ring-1 ring-blue-600/30 shadow-lg shadow-blue-950/30'
                    : 'bg-gray-900 border-gray-800'
                }`}
              >
                {plan.highlight && (
                  <div className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-3">Most Popular</div>
                )}
                <h3 className="text-xl font-bold text-white">{plan.name}</h3>
                <div className="mt-3 mb-1">
                  <span className="text-4xl font-black text-white">{plan.price}</span>
                  <span className="text-gray-500 text-sm">{plan.period}</span>
                </div>
                <p className="text-sm text-gray-400 mb-6">{plan.description}</p>
                <ul className="space-y-2.5 mb-8 flex-1">
                  {plan.features.map(f => (
                    <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                      <svg className="w-4 h-4 text-green-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                      {f}
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => handleCheckout(plan.priceId)}
                  className={`w-full py-3 rounded-lg font-semibold text-sm transition-all ${
                    plan.highlight
                      ? 'bg-blue-600 hover:bg-blue-700 text-white hover:shadow-lg hover:shadow-blue-600/25'
                      : 'bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700'
                  }`}
                >
                  {plan.cta}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-white mb-4">Ready to Catch Fraud?</h2>
          <p className="text-gray-400 mb-8 max-w-lg mx-auto">
            Join state Medicaid agencies and compliance teams using Inspector to protect taxpayer dollars.
          </p>
          <div className="flex items-center justify-center gap-3 max-w-md mx-auto">
            <input
              type="email"
              placeholder="Enter your email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="input flex-1"
            />
            <button onClick={onLogin} className="btn-primary whitespace-nowrap">
              Get Started
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8 px-6">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" className="w-5 h-5">
              <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
              <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" strokeWidth="4"/>
              <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
              <text x="28" y="33" textAnchor="middle" fontFamily="Arial" fontWeight="bold" fontSize="11" fill="#f59e0b">$</text>
              <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" strokeWidth="4.5" strokeLinecap="round"/>
            </svg>
            <span className="text-sm text-gray-500">Medicaid Inspector</span>
          </div>
          <p className="text-xs text-gray-600">Data sourced from CMS/HHS open datasets</p>
        </div>
      </footer>
    </div>
  )
}
