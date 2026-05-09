import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette
const PRICE_COLOR = '#60A5FA'   // chart-1
const VOLUME_COLOR = '#C9A84C'  // chart-2

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatVolume(value: number): string {
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return String(value)
}

export default function PriceChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data}>
            <XAxis
              dataKey="date"
              tick={{ fill: '#7A8299', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(d: string) => {
                const date = new Date(d)
                return `${date.getMonth() + 1}/${date.getDate()}`
              }}
              minTickGap={40}
            />
            <YAxis
              yAxisId="price"
              orientation="left"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(v: number) => `$${v}`}
            />
            <YAxis
              yAxisId="volume"
              orientation="right"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={formatVolume}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP}
              formatter={(value: number, name: string) => {
                if (name === 'Volume') return [formatVolume(value), name]
                return [`$${value.toFixed(2)}`, name]
              }}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar
              yAxisId="volume"
              dataKey="volume"
              name="Volume"
              fill={VOLUME_COLOR}
              opacity={0.3}
              barSize={4}
            />
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="close"
              name="Close"
              stroke={PRICE_COLOR}
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
