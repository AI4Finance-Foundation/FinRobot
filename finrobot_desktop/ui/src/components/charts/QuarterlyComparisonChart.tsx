import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { TooltipValueType } from 'recharts'

interface ChartProps {
  data: { quarter: string; revenue: number; operating_income: number; net_income: number }[]
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

function formatBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return String(v)
}

export default function QuarterlyComparisonChart({ data, title }: ChartProps) {
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
              dataKey="quarter"
              tick={{
                fill: '#7A8299',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
              }}
              axisLine={{ stroke: '#252A37' }}
              angle={-30}
              textAnchor="end"
              height={45}
            />
            <YAxis
              tickFormatter={formatBillions}
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <Tooltip
              formatter={(value: TooltipValueType | undefined) =>
                formatBillions(typeof value === 'number' ? value : 0)
              }
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: '#E8ECF4' }}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar dataKey="revenue" name="Revenue" fill="#60A5FA" radius={[2, 2, 0, 0]} />
            <Bar
              dataKey="operating_income"
              name="Operating Income"
              fill="#C9A84C"
              radius={[2, 2, 0, 0]}
            />
            <Bar dataKey="net_income" name="Net Income" fill="#34D399" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
