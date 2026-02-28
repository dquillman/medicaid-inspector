interface Props {
  score: number
  size?: 'sm' | 'md' | 'lg'
}

export default function RiskScoreBadge({ score, size = 'md' }: Props) {
  const isHighRisk = score >= 50

  const cls =
    score >= 70 ? 'badge-high' :
    score >= 40 ? 'badge-medium' :
    'badge-low'

  const label =
    score >= 70 ? 'HIGH' :
    score >= 50 ? 'ELEVATED' :
    score >= 40 ? 'MED' :
    'LOW'

  const textSize = size === 'lg' ? 'text-lg px-4 py-1.5' : size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <span
      className={`${cls} ${textSize} font-mono font-bold`}
      style={isHighRisk ? { animation: 'threat-pulse 2s ease-in-out infinite' } : undefined}
      title={`Risk Score: ${score.toFixed(1)}/100`}
    >
      {score.toFixed(0)} <span className="opacity-60 uppercase tracking-wider">{label}</span>
    </span>
  )
}
