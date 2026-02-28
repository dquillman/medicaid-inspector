interface Props {
  score: number
  size?: 'sm' | 'md' | 'lg'
}

export default function RiskScoreBadge({ score, size = 'md' }: Props) {
  const cls =
    score >= 70 ? 'badge-high' :
    score >= 40 ? 'badge-medium' :
    'badge-low'

  const label =
    score >= 70 ? 'HIGH' :
    score >= 40 ? 'MED' :
    'LOW'

  const textSize = size === 'lg' ? 'text-base px-3 py-1' : size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <span className={`${cls} ${textSize} font-mono font-bold`}>
      {score.toFixed(0)} <span className="opacity-60">{label}</span>
    </span>
  )
}
