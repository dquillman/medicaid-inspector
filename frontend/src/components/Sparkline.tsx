interface SparklineProps {
  data: number[]
  width?: number
  height?: number
}

export default function Sparkline({ data, width = 80, height = 24 }: SparklineProps) {
  if (data.length === 0) return null

  if (data.length === 1) {
    const cx = width / 2
    const cy = height / 2
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <circle cx={cx} cy={cy} r={3} fill="#6b7280" />
      </svg>
    )
  }

  const first = data[0]
  const last = data[data.length - 1]
  let color = '#6b7280'
  if (last > first * 1.1) color = '#ef4444'
  else if (last < first * 0.9) color = '#22c55e'

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const padding = 2

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width
    const y = padding + ((max - v) / range) * (height - padding * 2)
    return `${x},${y}`
  })

  const polylinePoints = points.join(' ')
  const polygonPoints = `${polylinePoints} ${width},${height} 0,${height}`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polygon points={polygonPoints} fill={color} opacity={0.2} />
      <polyline points={polylinePoints} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  )
}
