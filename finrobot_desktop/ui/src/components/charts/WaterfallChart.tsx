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
import type { TooltipValueType } from 'recharts'
import { useMemo } from 'react'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system colors
const POSITIVE_COLOR = '#34D399'
const NEGATIVE_COLOR = '#F87171'
const TOTAL_COLOR = '#C9A84C'

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

interface WaterfallBar {
  label: string
  value: number
  is_total: boolean
  base: number
  delta: number
  fill: string
}

export default function WaterfallChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  const bars = useMemo<WaterfallBar[]>(() => {
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
              tick={{ fill: '#4B5563', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#E2E5EB' }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={60}
            />
            <YAxis
              tick={{ fill: '#4B5563', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#E2E5EB' }}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP} labelStyle={{ color: 'var(--text-primary)' }}
              formatter={(
                _val: TooltipValueType | undefined,
                _name: string | number | undefined,
                // recharts Payload<> interface has payload?: any which carries the row data
                item: { payload?: WaterfallBar },
              ) => {
                const entry = item.payload
                if (!entry) return ['', '']
                if (entry.is_total) return [`$${entry.delta.toFixed(0)}`, 'Total']
                return [`$${entry.value.toFixed(0)}`, entry.value >= 0 ? 'Add' : 'Subtract']
              }}
            />
            <ReferenceLine y={0} stroke="#E2E5EB" />
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
