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

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
  currentPrice?: number | null
}

// Design system chart palette
const COLORS = ['var(--primary)', '#C9A84C', 'var(--success)', 'var(--secondary)', 'var(--warning)', 'var(--danger)']

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function FootballField({ data, title, currentPrice }: ChartProps) {
  if (!data || data.length === 0) return null

  const shaped = data.map((d) => ({
    method: String(d.method),
    low: Number(d.low),
    mid: Number(d.mid),
    high: Number(d.high),
    base: Number(d.low),
    range: Number(d.high) - Number(d.low),
  }))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
        {currentPrice != null && (
          <span className="card-badge">Current: ${currentPrice.toFixed(2)}</span>
        )}
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={Math.max(200, shaped.length * 50 + 60)}>
          <BarChart data={shaped} layout="vertical" barSize={20}>
            <XAxis
              type="number"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
              tickFormatter={(v: number) => `$${v}`}
            />
            <YAxis
              type="category"
              dataKey="method"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: 'var(--border-soft)' }}
              width={120}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP} labelStyle={{ color: 'var(--text-primary)' }}
              formatter={(value: TooltipValueType | undefined, name: string | number | undefined) => {
                const n = String(name ?? '')
                if (n === 'base') return [null, null]
                const v = typeof value === 'number' ? value : 0
                return [`$${v.toFixed(2)}`, 'Range Width']
              }}
              labelFormatter={(label: unknown) => {
                const s = String(label ?? '')
                const entry = shaped.find((e) => e.method === s)
                if (!entry) return s
                return `${s}: $${entry.low.toFixed(2)} \u2013 $${entry.high.toFixed(2)}`
              }}
            />
            <Bar dataKey="base" stackId="stack" fill="transparent" />
            <Bar dataKey="range" stackId="stack" radius={[0, 3, 3, 0]}>
              {shaped.map((_, index) => (
                <Cell key={`range-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Bar>
            {/* Current stock price reference line */}
            {currentPrice != null && (
              <ReferenceLine
                x={currentPrice}
                stroke="var(--bg-deep)"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                label={{
                  value: `$${currentPrice.toFixed(0)}`,
                  position: 'top',
                  fill: 'var(--bg-deep)',
                  fontSize: 11,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
