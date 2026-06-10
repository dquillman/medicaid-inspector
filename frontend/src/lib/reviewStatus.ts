/**
 * Shared review-status labels and colors — single source of truth.
 *
 * ProviderExplorer and ReviewQueue previously kept separate (and
 * disagreeing) copies; a status must render with the same label and
 * color on every screen.
 */
export const STATUS_LABELS: Record<string, string> = {
  pending:         'Pending',
  assigned:        'Assigned',
  investigating:   'Investigating',
  reviewed:        'Reviewed',
  confirmed_fraud: 'Confirmed Fraud',
  referred:        'Referred',
  dismissed:       'Dismissed',
}

export const STATUS_COLORS: Record<string, string> = {
  pending:         'text-yellow-400 bg-yellow-400/10',
  assigned:        'text-cyan-400 bg-cyan-400/10',
  investigating:   'text-purple-400 bg-purple-400/10',
  reviewed:        'text-blue-400 bg-blue-400/10',
  confirmed_fraud: 'text-red-400 bg-red-400/10',
  referred:        'text-orange-400 bg-orange-400/10',
  dismissed:       'text-gray-500 bg-gray-500/10',
}
