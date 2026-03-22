interface EmptyStateProps {
  variant: 'no-results' | 'no-data' | 'no-providers' | 'error'
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
}

function Illustration({ variant }: { variant: EmptyStateProps['variant'] }) {
  switch (variant) {
    case 'no-results':
      return (
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <circle cx="28" cy="28" r="16" stroke="#4b5563" strokeWidth="2.5" fill="#1f2937" />
          <line x1="39" y1="39" x2="54" y2="54" stroke="#4b5563" strokeWidth="2.5" strokeLinecap="round" />
          <line x1="22" y1="22" x2="34" y2="34" stroke="#4b5563" strokeWidth="2" strokeLinecap="round" />
          <line x1="34" y1="22" x2="22" y2="34" stroke="#4b5563" strokeWidth="2" strokeLinecap="round" />
        </svg>
      )
    case 'no-data':
      return (
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <line x1="13" y1="48" x2="13" y2="28" stroke="#4b5563" strokeWidth="2" strokeDasharray="3 2" />
          <line x1="28" y1="48" x2="28" y2="18" stroke="#4b5563" strokeWidth="2" strokeDasharray="3 2" />
          <line x1="43" y1="48" x2="43" y2="34" stroke="#4b5563" strokeWidth="2" strokeDasharray="3 2" />
          <line x1="58" y1="48" x2="58" y2="12" stroke="#4b5563" strokeWidth="2" strokeDasharray="3 2" />
          <line x1="4" y1="48" x2="60" y2="48" stroke="#4b5563" strokeWidth="2" />
          <line x1="4" y1="48" x2="4" y2="8" stroke="#4b5563" strokeWidth="2" />
        </svg>
      )
    case 'no-providers':
      return (
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <circle cx="28" cy="20" r="10" stroke="#4b5563" strokeWidth="2.5" fill="#1f2937" />
          <path d="M12 52c0-8.837 7.163-16 16-16s16 7.163 16 16" stroke="#4b5563" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          <text x="46" y="28" fontSize="20" fontWeight="bold" fill="#4b5563" fontFamily="sans-serif">?</text>
        </svg>
      )
    case 'error':
      return (
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M32 8L4 56h56L32 8z" stroke="#991b1b" strokeWidth="2.5" fill="none" strokeLinejoin="round" />
          <line x1="32" y1="26" x2="32" y2="40" stroke="#991b1b" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="32" cy="47" r="2" fill="#991b1b" />
        </svg>
      )
  }
}

export default function EmptyState({ variant, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <Illustration variant={variant} />
      <p className="text-lg font-medium text-gray-400 mt-4">{title}</p>
      {description && <p className="text-sm text-gray-600 mt-1">{description}</p>}
      {action && (
        <button className="btn-primary mt-4" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  )
}
