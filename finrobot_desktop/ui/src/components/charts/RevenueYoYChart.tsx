import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'
import type { TooltipValueType } from 'recharts'

interface ChartProps {
  data: { year: string; yoy_pct: number | null }[]
  title: string
}

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatPct(v: number): string {
  return `${v.toFixed(1)}%`
}

export default function RevenueYoYChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  // Filter out null yoy_pct for rendering; keep nulls as 0 for bar shape
  const chartData = data.map((d) => ({ ...d, yoy_pct: d.yoy_pct ?? 0 }))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chartData} barGap={2}>
            <XAxis
              dataKey="year"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <YAxis
              tickFormatter={formatPct}
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <Tooltip
              formatter={(value: TooltipValueType | undefined) =>
                formatPct(typeof value === 'number' ? value : 0)
              }
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: 'var(--text-primary)' }}
            />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
            <ReferenceLine y={0} stroke="var(--border-soft)" strokeWidth={1} />
            <Bar dataKey="yoy_pct" name="YoY Growth %" radius={[2, 2, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell
                  key={`yoy-${index}`}
                  fill={(entry.yoy_pct ?? 0) >= 0 ? 'var(--success)' : 'var(--danger)'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
