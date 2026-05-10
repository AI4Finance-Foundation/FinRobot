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
const COMPANY_COLOR = '#60A5FA'  // chart-1
const BENCHMARK_COLOR = '#C9A84C' // chart-2

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
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
            <PolarGrid stroke="#252A37" />
            <PolarAngleAxis
              dataKey="dimension"
              tick={{ fill: '#7A8299', fontSize: 11 }}
            />
            <PolarRadiusAxis
              tick={{ fill: '#4A5168', fontSize: 10 }}
              axisLine={false}
            />
            <Tooltip contentStyle={CHART_TOOLTIP} labelStyle={{ color: "#E8ECF4" }} />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
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
