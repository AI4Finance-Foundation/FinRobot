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
            {/* `value` is the TARGET company (compsResultToRadarData maps
              t.pe_ratio/… → value); `benchmark` is the peer-median ring pinned
              at 100. Render the target as the unmistakable hero — thicker,
              brighter stroke + denser fill — and dim the peer-median series so
              the subject reads first (Bloomberg EQRV subject-vs-peer emphasis).
              The benchmark also drops to a thin dashed ring so it reads as a
              reference outline, not a competing shape. */}
            <Radar
              name={t('chart.radar.benchmark')}
              dataKey="benchmark"
              stroke={BENCHMARK_COLOR}
              strokeWidth={1}
              strokeOpacity={0.55}
              strokeDasharray="4 3"
              fill={BENCHMARK_COLOR}
              fillOpacity={0.08}
            />
            <Radar
              name={t('chart.radar.company')}
              dataKey="value"
              stroke={COMPANY_COLOR}
              strokeWidth={2.5}
              fill={COMPANY_COLOR}
              fillOpacity={0.32}
              dot={{ fill: COMPANY_COLOR, r: 2.5, strokeWidth: 0 }}
            />
          </RechartsRadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
