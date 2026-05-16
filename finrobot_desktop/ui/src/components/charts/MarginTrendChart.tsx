import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { TooltipValueType } from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette (matches v3 tokens in App.css)
const COLORS = {
  gross_margin: '#10B981',     // chart-2 (green)
  ebitda_margin: '#8B5CF6',    // chart-4 (purple)
  operating_margin: '#3B82F6', // chart-1 (blue)
}

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export default function MarginTrendChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data}>
            <defs>
              <linearGradient id="grossGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.gross_margin} stopOpacity={0.12} />
                <stop offset="95%" stopColor={COLORS.gross_margin} stopOpacity={0.01} />
              </linearGradient>
              <linearGradient id="ebitdaGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.ebitda_margin} stopOpacity={0.10} />
                <stop offset="95%" stopColor={COLORS.ebitda_margin} stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="year"
              tick={{ fill: '#4B5563', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#E2E5EB' }}
            />
            <YAxis
              tickFormatter={formatPercent}
              tick={{ fill: '#4B5563', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#E2E5EB' }}
            />
            <Tooltip
              formatter={(value: TooltipValueType | undefined) =>
                formatPercent(typeof value === 'number' ? value : 0)
              }
              contentStyle={CHART_TOOLTIP} labelStyle={{ color: 'var(--text-primary)' }}
            />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
            <Area
              type="monotone"
              dataKey="gross_margin"
              name="Gross"
              stroke={COLORS.gross_margin}
              strokeWidth={2}
              fill="url(#grossGradient)"
              dot={{ r: 3, fill: COLORS.gross_margin }}
            />
            <Area
              type="monotone"
              dataKey="ebitda_margin"
              name="EBITDA"
              stroke={COLORS.ebitda_margin}
              strokeWidth={2}
              fill="url(#ebitdaGradient)"
              dot={{ r: 3, fill: COLORS.ebitda_margin }}
            />
            <Line
              type="monotone"
              dataKey="operating_margin"
              name="Operating"
              stroke={COLORS.operating_margin}
              strokeWidth={2}
              dot={{ r: 3, fill: COLORS.operating_margin }}
              opacity={0.7}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
