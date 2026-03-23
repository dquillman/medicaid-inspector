import React from 'react'
import { Link, useLocation } from 'react-router-dom'

const LABELS: Record<string, string> = {
  'providers': 'Providers',
  'anomalies': 'Anomalies',
  'network': 'Network',
  'review': 'Review Queue',
  'watchlist': 'Watchlist',
  'geographic': 'Geographic',
  'rings': 'Fraud Rings',
  'hotspots': 'Fraud Hotspots',
  'billing-codes': 'Billing Codes',
  'claim-patterns': 'Claim Patterns',
  'beneficiary-fraud': 'Beneficiary Fraud',
  'pharmacy-dme': 'Pharmacy & DME',
  'news': 'News & Legal',
  'demographics': 'Demographics',
  'trends': 'Trends',
  'utilization': 'Utilization',
  'population': 'Population',
  'density': 'Density Map',
  'admin': 'Admin',
  'scan': 'Scan & Data',
  'alerts': 'Alert Rules',
  'audit': 'Audit Log',
  'roi': 'ROI Dashboard',
  'ownership': 'Ownership',
  'ml-model': 'ML Model',
  'users': 'User Management',
}

function isNPI(segment: string): boolean {
  return /^\d{10}$/.test(segment)
}

interface BreadcrumbItem {
  label: string
  path: string
}

export default function Breadcrumbs() {
  const location = useLocation()
  const segments = location.pathname.split('/').filter((s) => s !== '')

  if (segments.length === 0) return null

  const items: BreadcrumbItem[] = [{ label: 'Home', path: '/' }]
  let accumulated = ''
  for (const seg of segments) {
    accumulated += '/' + seg
    const label = isNPI(seg) ? seg : (LABELS[seg] ?? seg)
    items.push({ label, path: accumulated })
  }

  return (
    <nav className="no-print px-4 md:px-6 py-2 text-xs flex items-center gap-1.5">
      {items.map((item, i) => (
        <React.Fragment key={item.path}>
          {i > 0 && <span className="text-gray-700">/</span>}
          {i === items.length - 1 ? (
            <span className="text-white font-medium">{item.label}</span>
          ) : (
            <Link to={item.path} className="text-gray-500 hover:text-gray-300 transition-colors">
              {item.label}
            </Link>
          )}
        </React.Fragment>
      ))}
    </nav>
  )
}
