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
import type { TooltipValueType } from 'recharts'

interface ChartProps {
  data: { year: string; operating: number; investing: number; financing: number }[]
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

export default function CashFlowChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  const enriched = data.map((d) => ({
    ...d,
    net: d.operating + d.investing + d.financing,
  }))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={enriched} barGap={2}>
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
              formatter={(value: TooltipValueType | undefined) =>
                formatBillions(typeof value === 'number' ? value : 0)
              }
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: '#E8ECF4' }}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar dataKey="operating" name="Operating" fill="#34D399" radius={[2, 2, 0, 0]} />
            <Bar dataKey="investing" name="Investing" fill="#F87171" radius={[2, 2, 0, 0]} />
            <Bar dataKey="financing" name="Financing" fill="#C9A84C" radius={[2, 2, 0, 0]} />
            <Line
              type="monotone"
              dataKey="net"
              name="Net Cash Flow"
              stroke="#60A5FA"
              strokeWidth={2}
              dot={{ r: 3, fill: '#60A5FA' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
