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

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
  currentPrice?: number | null
}

// Design system chart palette
const COLORS = ['#60A5FA', '#C9A84C', '#34D399', '#A78BFA', '#FB923C', '#F87171']

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
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
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(v: number) => `$${v}`}
            />
            <YAxis
              type="category"
              dataKey="method"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              width={120}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP}
              formatter={(value: number, name: string) => {
                if (name === 'base') return [null, null]
                return [`$${value.toFixed(2)}`, 'Range Width']
              }}
              labelFormatter={(label: string) => {
                const entry = shaped.find((s) => s.method === label)
                if (!entry) return label
                return `${label}: $${entry.low.toFixed(2)} – $${entry.high.toFixed(2)}`
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
                stroke="#E8ECF4"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                label={{
                  value: `$${currentPrice.toFixed(0)}`,
                  position: 'top',
                  fill: '#E8ECF4',
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
