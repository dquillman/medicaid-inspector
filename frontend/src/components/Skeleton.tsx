interface SkeletonLineProps {
  width?: string
}

export function SkeletonLine({ width = '100%' }: SkeletonLineProps) {
  return <div className="h-4 rounded animate-shimmer" style={{ width }} />
}

export function SkeletonCard() {
  return (
    <div className="card space-y-3">
      <SkeletonLine width="100%" />
      <SkeletonLine width="75%" />
      <SkeletonLine width="60%" />
    </div>
  )
}

interface SkeletonTableProps {
  rows: number
  columns: number
}

export function SkeletonTable({ rows, columns }: SkeletonTableProps) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-gray-800 bg-gray-900/80">
          {Array.from({ length: columns }).map((_, c) => (
            <th key={c} className="px-4 py-3">
              <div className="h-3 rounded animate-shimmer w-16" />
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-800">
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r}>
            {Array.from({ length: columns }).map((_, c) => (
              <td key={c} className="px-4 py-3">
                <div
                  className="h-4 rounded animate-shimmer"
                  style={{ width: c === 0 ? '80px' : `${60 + ((r + c) % 3) * 15}%` }}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function SkeletonChart() {
  return <div className="h-64 rounded-lg animate-shimmer" />
}

export function SkeletonKPI() {
  return (
    <div className="card py-3 flex flex-col items-center gap-2">
      <div className="h-3 rounded animate-shimmer w-24" />
      <div className="h-10 rounded animate-shimmer w-20" />
      <div className="h-3 rounded animate-shimmer w-32" />
    </div>
  )
}
