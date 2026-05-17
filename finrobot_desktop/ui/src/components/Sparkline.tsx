/**
 * Sparkline — tiny inline price chart, pure SVG (no recharts).
 *
 * Designed for Sidebar WatchlistItem and similar compact contexts. Color is
 * derived from net change (first→last). Skeleton on empty data.
 *
 * Honest: returns null when fewer than 2 points exist — never fakes a line.
 */

import { useMemo } from 'react'

interface Props {
  /** Closing prices in chronological order (oldest → newest). */
  values: number[]
  /** Width in pixels. */
  width?: number
  /** Height in pixels. */
  height?: number
  /** Optional override; otherwise computed from first→last direction. */
  color?: string
  /** Render a thin fill below the line for emphasis. */
  fill?: boolean
}

export function Sparkline({
  values,
  width = 48,
  height = 14,
  color,
  fill = false,
}: Props): React.ReactElement | null {
  const path = useMemo(() => {
    if (values.length < 2) return null
    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = max - min || 1
    const stepX = width / (values.length - 1)
    const points = values.map((v, i) => {
      const x = i * stepX
      // Invert y because SVG origin is top-left
      const y = height - ((v - min) / range) * height
      return [x, y] as const
    })
    const linePath = points
      .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(' ')
    const lastY = points[points.length - 1][1]
    const firstY = points[0][1]
    const fillPath = fill
      ? `${linePath} L${width.toFixed(1)},${height} L0,${height} Z`
      : null
    return { linePath, fillPath, firstY, lastY, points }
  }, [values, width, height, fill])

  if (!path) return null

  const auto = values[values.length - 1] >= values[0] ? 'var(--positive)' : 'var(--negative)'
  const stroke = color ?? auto

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      style={{ display: 'block', flexShrink: 0 }}
    >
      {path.fillPath && (
        <path d={path.fillPath} fill={stroke} fillOpacity={0.15} stroke="none" />
      )}
      <path d={path.linePath} fill="none" stroke={stroke} strokeWidth={1.2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
