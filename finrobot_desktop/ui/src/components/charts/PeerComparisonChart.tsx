import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'
import type { TooltipValueType } from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette
const PRIMARY = 'var(--primary)' // chart-1
const ACCENT = '#C9A84C' // chart-2
const TARGET_HIGHLIGHT = 'var(--warning)' // chart-5

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function PeerComparisonChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} barGap={2}>
            <XAxis
              dataKey="ticker"
              tick={{
                fill: 'var(--text-muted)',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
              }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <YAxis
              tick={{
                fill: 'var(--text-muted)',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
              }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <Tooltip
              formatter={(value: TooltipValueType | undefined) => {
                const v = typeof value === 'number' ? value : 0
                return v.toFixed(1)
              }}
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: 'var(--text-primary)' }}
            />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
            <Bar dataKey="ev_ebitda" name="EV/EBITDA" radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`ev-${index}`} fill={entry.is_target ? TARGET_HIGHLIGHT : PRIMARY} />
              ))}
            </Bar>
            <Bar dataKey="pe_ratio" name="P/E Ratio" radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`pe-${index}`} fill={entry.is_target ? TARGET_HIGHLIGHT : ACCENT} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
