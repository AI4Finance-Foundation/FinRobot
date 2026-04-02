import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const PRIMARY = '#1a365d'
const ACCENT = '#d4a843'
const FORECAST_PRIMARY = '#1a365d99'
const FORECAST_ACCENT = '#d4a84399'

function formatBillions(value: number): string {
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${value.toLocaleString()}`
}

export default function RevenueEbitdaChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} barGap={4}>
          <XAxis
            dataKey="year"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <YAxis
            tickFormatter={formatBillions}
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <Tooltip
            formatter={(value: number) => formatBillions(value)}
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
          />
          <Legend wrapperStyle={{ color: '#9ca3af' }} />
          <Bar dataKey="revenue" name="Revenue" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={`rev-${index}`}
                fill={entry.is_forecast ? FORECAST_PRIMARY : PRIMARY}
              />
            ))}
          </Bar>
          <Bar dataKey="ebitda" name="EBITDA" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={`ebitda-${index}`}
                fill={entry.is_forecast ? FORECAST_ACCENT : ACCENT}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
