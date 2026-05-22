import {
  RadarChart as RechartsRadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Legend,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette
const COMPANY_COLOR = 'var(--primary)'  // chart-1
const BENCHMARK_COLOR = '#C9A84C' // chart-2

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function CompanyRadarChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={300}>
          <RechartsRadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
            <PolarGrid stroke="var(--border-soft)" />
            <PolarAngleAxis
              dataKey="dimension"
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            />
            <PolarRadiusAxis
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              axisLine={false}
            />
            <Tooltip contentStyle={CHART_TOOLTIP} labelStyle={{ color: 'var(--text-primary)' }} />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
            <Radar
              name="Company"
              dataKey="value"
              stroke={COMPANY_COLOR}
              fill={COMPANY_COLOR}
              fillOpacity={0.25}
            />
            <Radar
              name="Benchmark"
              dataKey="benchmark"
              stroke={BENCHMARK_COLOR}
              fill={BENCHMARK_COLOR}
              fillOpacity={0.15}
            />
          </RechartsRadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
