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

const PRIMARY = '#1a365d'
const ACCENT = '#d4a843'

function formatVolume(value: number): string {
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return String(value)
}

export default function PriceChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <XAxis
            dataKey="date"
            tick={{ fill: '#9ca3af', fontSize: 10 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={(d: string) => {
              const date = new Date(d)
              return `${date.getMonth() + 1}/${date.getDate()}`
            }}
            minTickGap={40}
          />
          <YAxis
            yAxisId="price"
            orientation="left"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={(v: number) => `$${v}`}
          />
          <YAxis
            yAxisId="volume"
            orientation="right"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={formatVolume}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
            formatter={(value: number, name: string) => {
              if (name === 'Volume') return [formatVolume(value), name]
              return [`$${value.toFixed(2)}`, name]
            }}
          />
          <Legend wrapperStyle={{ color: '#9ca3af' }} />
          <Bar
            yAxisId="volume"
            dataKey="volume"
            name="Volume"
            fill={ACCENT}
            opacity={0.3}
            barSize={4}
          />
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="close"
            name="Close"
            stroke={PRIMARY}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
