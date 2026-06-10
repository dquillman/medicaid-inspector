import { riskBadgeClass, riskLabel } from '../lib/risk'

interface Props {
  score: number
  size?: 'sm' | 'md' | 'lg'
}

export default function RiskScoreBadge({ score, size = 'md' }: Props) {
  const textSize = size === 'lg' ? 'text-lg px-4 py-1.5' : size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <span
      className={`${riskBadgeClass(score)} ${textSize} font-mono font-bold`}
      title={`Risk Score: ${score.toFixed(1)}/100`}
    >
      {score.toFixed(0)} <span className="opacity-60 uppercase tracking-wider">{riskLabel(score)}</span>
    </span>
  )
}
