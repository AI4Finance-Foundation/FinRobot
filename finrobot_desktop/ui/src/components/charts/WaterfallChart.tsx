import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'
import { useMemo } from 'react'

import { fmtUsd } from '../../utils/formatters'
import { CosmicTooltipShell, CosmicTooltipRow } from './chartTooltip'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system colors
const POSITIVE_COLOR = 'var(--success)'
const NEGATIVE_COLOR = 'var(--danger)'
const TOTAL_COLOR = 'var(--chart-gold)'

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
}

interface WaterfallBar {
  label: string
  value: number
  is_total: boolean
  base: number
  delta: number
  fill: string
}

// Bespoke content (Add / Subtract / Total) but the shared cosmic shell so it
// matches every other chart's tooltip rather than the old low-contrast box.
function WaterfallTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: { payload?: WaterfallBar }[]
}) {
  const entry = active ? payload?.[0]?.payload : undefined
  if (!entry) return null
  const name = entry.is_total ? 'Total' : entry.value >= 0 ? 'Add' : 'Subtract'
  return (
    <CosmicTooltipShell label={entry.label}>
      <CosmicTooltipRow
        color={entry.fill}
        name={name}
        value={fmtUsd(entry.is_total ? entry.delta : entry.value)}
      />
    </CosmicTooltipShell>
  )
}

export default function WaterfallChart({ data, title }: ChartProps) {
  const bars = useMemo<WaterfallBar[]>(() => {
    if (!data || data.length === 0) return []
    let runningTotal = 0
    return data.map((d) => {
      const value = Number(d.value)
      const isTotal = Boolean(d.is_total)

      if (isTotal) {
        const bar: WaterfallBar = {
          label: String(d.label),
          value,
          is_total: true,
          base: 0,
          delta: runningTotal,
          fill: TOTAL_COLOR,
        }
        return bar
      }

      const base = runningTotal
      runningTotal += value
      return {
        label: String(d.label),
        value,
        is_total: false,
        base: value >= 0 ? base : base + value,
        delta: Math.abs(value),
        fill: value >= 0 ? POSITIVE_COLOR : NEGATIVE_COLOR,
      }
    })
  }, [data])

  if (bars.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={bars}>
            <XAxis
              dataKey="label"
              tick={AXIS_TICK}
              axisLine={{ stroke: 'var(--border-soft)' }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={60}
            />
            <YAxis
              tick={AXIS_TICK}
              axisLine={{ stroke: 'var(--border-soft)' }}
              // Large values (e.g. AAPL terminal value ~$1.2T) need abbreviated
              // ticks — raw `${v}` overflowed the Y-axis gutter and rendered as
              // a clipped run of zeros in the production screenshot.
              tickFormatter={fmtUsd}
              width={60}
            />
            <Tooltip
              content={<WaterfallTooltip />}
              cursor={{ fill: 'var(--primary-soft)', radius: 4 }}
            />
            <ReferenceLine y={0} stroke="var(--border-soft)" />
            <Bar dataKey="base" stackId="waterfall" fill="transparent" />
            <Bar dataKey="delta" stackId="waterfall" radius={[3, 3, 0, 0]}>
              {bars.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
