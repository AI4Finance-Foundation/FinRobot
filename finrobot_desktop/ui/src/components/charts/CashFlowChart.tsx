import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { TooltipValueType } from 'recharts'

interface ChartProps {
  data: { year: string; operating: number; investing: number; financing: number }[]
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

function formatBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return String(v)
}

export default function CashFlowChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  const enriched = data.map((d) => ({
    ...d,
    net: d.operating + d.investing + d.financing,
  }))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={enriched} barGap={2}>
            <XAxis
              dataKey="year"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <YAxis
              tickFormatter={formatBillions}
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <Tooltip
              formatter={(value: TooltipValueType | undefined) =>
                formatBillions(typeof value === 'number' ? value : 0)
              }
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: 'var(--text-primary)' }}
            />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
            <Bar dataKey="operating" name="Operating" fill="var(--success)" radius={[2, 2, 0, 0]} />
            <Bar dataKey="investing" name="Investing" fill="var(--danger)" radius={[2, 2, 0, 0]} />
            <Bar dataKey="financing" name="Financing" fill="#C9A84C" radius={[2, 2, 0, 0]} />
            <Line
              type="monotone"
              dataKey="net"
              name="Net Cash Flow"
              stroke="var(--primary)"
              strokeWidth={2}
              dot={{ r: 3, fill: 'var(--primary)' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
