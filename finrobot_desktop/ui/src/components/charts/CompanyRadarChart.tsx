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
import { useI18n } from '../../i18n'
import { CosmicTooltip, CosmicLegend } from './chartTooltip'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette
const COMPANY_COLOR = 'var(--primary)' // chart-1
const BENCHMARK_COLOR = 'var(--chart-gold)' // gold, distinct from the blue company trace

export default function CompanyRadarChart({ data, title }: ChartProps) {
  const { t } = useI18n()
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
            <PolarRadiusAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} />
            <Tooltip content={<CosmicTooltip format={(v) => v.toFixed(1)} />} />
            <Legend content={<CosmicLegend />} />
            <Radar
              name={t('chart.radar.company')}
              dataKey="value"
              stroke={COMPANY_COLOR}
              fill={COMPANY_COLOR}
              fillOpacity={0.25}
            />
            <Radar
              name={t('chart.radar.benchmark')}
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
