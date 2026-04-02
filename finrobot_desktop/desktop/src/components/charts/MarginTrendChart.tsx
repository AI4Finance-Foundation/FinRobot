import {
  LineChart,
  Line,
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

const COLORS = {
  gross_margin: '#d4a843',
  ebitda_margin: '#1a365d',
  operating_margin: '#6b7280',
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export default function MarginTrendChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <XAxis
            dataKey="year"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <YAxis
            tickFormatter={formatPercent}
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <Tooltip
            formatter={(value: number) => formatPercent(value)}
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
          />
          <Legend wrapperStyle={{ color: '#9ca3af' }} />
          <Line
            type="monotone"
            dataKey="gross_margin"
            name="Gross Margin"
            stroke={COLORS.gross_margin}
            strokeWidth={2}
            dot={{ r: 4, fill: COLORS.gross_margin }}
          />
          <Line
            type="monotone"
            dataKey="ebitda_margin"
            name="EBITDA Margin"
            stroke={COLORS.ebitda_margin}
            strokeWidth={2}
            dot={{ r: 4, fill: COLORS.ebitda_margin }}
          />
          <Line
            type="monotone"
            dataKey="operating_margin"
            name="Operating Margin"
            stroke={COLORS.operating_margin}
            strokeWidth={2}
            dot={{ r: 4, fill: COLORS.operating_margin }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
