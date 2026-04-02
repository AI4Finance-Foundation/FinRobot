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

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const POSITIVE_COLOR = '#22c55e'
const NEGATIVE_COLOR = '#ef4444'
const TOTAL_COLOR = '#1a365d'

interface WaterfallBar {
  label: string
  value: number
  is_total: boolean
  base: number
  delta: number
  fill: string
}

/**
 * Waterfall chart: each non-total bar floats from a running base.
 * Total bars always start from 0 and go to the cumulative value.
 */
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
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={bars}>
          <XAxis
            dataKey="label"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            axisLine={{ stroke: '#4b5563' }}
            interval={0}
            angle={-30}
            textAnchor="end"
            height={60}
          />
          <YAxis
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={(v: number) => `$${v}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
            formatter={(_val: number, _name: string, props: { payload: WaterfallBar }) => {
              const entry = props.payload
              if (entry.is_total) return [`$${entry.delta.toFixed(0)}`, 'Total']
              return [`$${entry.value.toFixed(0)}`, entry.value >= 0 ? 'Add' : 'Subtract']
            }}
          />
          <ReferenceLine y={0} stroke="#4b5563" />
          {/* Invisible base bar */}
          <Bar dataKey="base" stackId="waterfall" fill="transparent" />
          {/* Visible delta bar */}
          <Bar dataKey="delta" stackId="waterfall" radius={[4, 4, 0, 0]}>
            {bars.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
