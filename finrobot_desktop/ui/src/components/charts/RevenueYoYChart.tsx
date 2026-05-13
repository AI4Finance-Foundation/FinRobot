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

interface ChartProps {
  data: { year: string; yoy_pct: number | null }[]
  title: string
}

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
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
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <YAxis
              tickFormatter={formatPct}
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <Tooltip
              formatter={(value: number) => formatPct(value)}
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: '#E8ECF4' }}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <ReferenceLine y={0} stroke="#252A37" strokeWidth={1} />
            <Bar dataKey="yoy_pct" name="YoY Growth %" radius={[2, 2, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell
                  key={`yoy-${index}`}
                  fill={(entry.yoy_pct ?? 0) >= 0 ? '#34D399' : '#F87171'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

