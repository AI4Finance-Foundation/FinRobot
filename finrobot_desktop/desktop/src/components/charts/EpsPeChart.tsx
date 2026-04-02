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

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const PRIMARY = '#1a365d'
const ACCENT = '#d4a843'

export default function EpsPeChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <XAxis
            dataKey="year"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <YAxis
            yAxisId="eps"
            orientation="left"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            label={{
              value: 'EPS',
              angle: -90,
              position: 'insideLeft',
              fill: '#9ca3af',
              fontSize: 12,
            }}
          />
          <YAxis
            yAxisId="pe"
            orientation="right"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={(v: number) => `${v.toFixed(0)}x`}
            label={{
              value: 'P/E',
              angle: 90,
              position: 'insideRight',
              fill: '#9ca3af',
              fontSize: 12,
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
            formatter={(value: number, name: string) => {
              if (name === 'P/E Ratio') return [`${value.toFixed(1)}x`, name]
              return [`$${value.toFixed(2)}`, name]
            }}
          />
          <Legend wrapperStyle={{ color: '#9ca3af' }} />
          <Bar
            yAxisId="eps"
            dataKey="eps"
            name="EPS"
            fill={PRIMARY}
            radius={[4, 4, 0, 0]}
          />
          <Line
            yAxisId="pe"
            type="monotone"
            dataKey="pe_ratio"
            name="P/E Ratio"
            stroke={ACCENT}
            strokeWidth={2}
            dot={{ r: 4, fill: ACCENT }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
