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

// Design system chart palette
const REVENUE_COLOR = '#60A5FA'      // chart-1
const EBITDA_COLOR = '#C9A84C'       // chart-2
const FORECAST_REVENUE = 'rgba(96, 165, 250, 0.45)'
const FORECAST_EBITDA = 'rgba(201, 168, 76, 0.45)'

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatBillions(value: number): string {
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${value.toLocaleString()}`
}

export default function RevenueEbitdaChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} barGap={2}>
            <XAxis
              dataKey="year"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <YAxis
              tickFormatter={formatBillions}
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <Tooltip
              formatter={(value: number) => formatBillions(value)}
              contentStyle={CHART_TOOLTIP}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar dataKey="revenue" name="Revenue" radius={[2, 2, 0, 0]}>
              {data.map((entry, index) => (
                <Cell
                  key={`rev-${index}`}
                  fill={entry.is_forecast ? FORECAST_REVENUE : REVENUE_COLOR}
                />
              ))}
            </Bar>
            <Bar dataKey="ebitda" name="EBITDA" radius={[2, 2, 0, 0]}>
              {data.map((entry, index) => (
                <Cell
                  key={`ebitda-${index}`}
                  fill={entry.is_forecast ? FORECAST_EBITDA : EBITDA_COLOR}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
