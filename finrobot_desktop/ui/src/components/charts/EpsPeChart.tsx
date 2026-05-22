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
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette
const EPS_COLOR = 'var(--primary)'   // chart-1
const PE_COLOR = '#C9A84C'    // chart-2

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function EpsPeChart({ data, title }: ChartProps) {
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
              <linearGradient id="epsBarGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={EPS_COLOR} stopOpacity={0.85} />
                <stop offset="100%" stopColor={EPS_COLOR} stopOpacity={0.45} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="year"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <YAxis
              yAxisId="eps"
              orientation="left"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              label={{
                value: 'EPS',
                angle: -90,
                position: 'insideLeft',
                fill: 'var(--text-muted)',
                fontSize: 11,
              }}
            />
            <YAxis
              yAxisId="pe"
              orientation="right"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
              tickFormatter={(v: number) => `${v.toFixed(0)}x`}
              label={{
                value: 'P/E',
                angle: 90,
                position: 'insideRight',
                fill: 'var(--text-muted)',
                fontSize: 11,
              }}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP} labelStyle={{ color: 'var(--text-primary)' }}
              formatter={(value: TooltipValueType | undefined, name: string | number | undefined) => {
                const v = typeof value === 'number' ? value : 0
                const n = String(name ?? '')
                if (n === 'P/E Ratio') return [`${v.toFixed(1)}x`, n]
                return [`$${v.toFixed(2)}`, n]
              }}
            />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
            <Bar
              yAxisId="eps"
              dataKey="eps"
              name="EPS"
              fill="url(#epsBarGradient)"
              radius={[3, 3, 0, 0]}
            />
            <Line
              yAxisId="pe"
              type="monotone"
              dataKey="pe_ratio"
              name="P/E Ratio"
              stroke={PE_COLOR}
              strokeWidth={2}
              dot={{ r: 3, fill: PE_COLOR }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
