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
const PRIMARY = '#60A5FA'         // chart-1
const ACCENT = '#C9A84C'          // chart-2
const TARGET_HIGHLIGHT = '#FB923C' // chart-5

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function PeerComparisonChart({ data, title }: ChartProps) {
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
              dataKey="ticker"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <YAxis
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
            />
            <Tooltip
              formatter={(value: number) => value.toFixed(1)}
              contentStyle={CHART_TOOLTIP}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar dataKey="ev_ebitda" name="EV/EBITDA" radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell
                  key={`ev-${index}`}
                  fill={entry.is_target ? TARGET_HIGHLIGHT : PRIMARY}
                />
              ))}
            </Bar>
            <Bar dataKey="pe_ratio" name="P/E Ratio" radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell
                  key={`pe-${index}`}
                  fill={entry.is_target ? TARGET_HIGHLIGHT : ACCENT}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
