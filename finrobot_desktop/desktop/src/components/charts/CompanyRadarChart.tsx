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

const PRIMARY = '#1a365d'
const ACCENT = '#d4a843'

export default function CompanyRadarChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={350}>
        <RechartsRadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
          <PolarGrid stroke="#4b5563" />
          <PolarAngleAxis
            dataKey="dimension"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
          />
          <PolarRadiusAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
          />
          <Legend wrapperStyle={{ color: '#9ca3af' }} />
          <Radar
            name="Company"
            dataKey="value"
            stroke={PRIMARY}
            fill={PRIMARY}
            fillOpacity={0.3}
          />
          <Radar
            name="Benchmark"
            dataKey="benchmark"
            stroke={ACCENT}
            fill={ACCENT}
            fillOpacity={0.2}
          />
        </RechartsRadarChart>
      </ResponsiveContainer>
    </div>
  )
}
