import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useI18n } from '../../i18n'
import { CosmicTooltip, CosmicLegend } from './chartTooltip'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// Design system chart palette (matches v3 tokens in App.css)
const COLORS = {
  gross_margin: 'var(--success)', // chart-2 (green)
  ebitda_margin: 'var(--secondary)', // chart-4 (purple)
  operating_margin: 'var(--primary)', // chart-1 (blue)
}

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export default function MarginTrendChart({ data, title }: ChartProps) {
  const { t } = useI18n()
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data}>
            <defs>
              <linearGradient id="grossGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.gross_margin} stopOpacity={0.12} />
                <stop offset="95%" stopColor={COLORS.gross_margin} stopOpacity={0.01} />
              </linearGradient>
              <linearGradient id="ebitdaGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.ebitda_margin} stopOpacity={0.1} />
                <stop offset="95%" stopColor={COLORS.ebitda_margin} stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <XAxis dataKey="year" tick={AXIS_TICK} axisLine={{ stroke: 'var(--border-soft)' }} />
            <YAxis
              tickFormatter={formatPercent}
              tick={AXIS_TICK}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <Tooltip
              content={<CosmicTooltip format={formatPercent} />}
              cursor={{ stroke: 'var(--border-glow)', strokeWidth: 1 }}
            />
            <Legend content={<CosmicLegend />} />
            <Area
              type="monotone"
              dataKey="gross_margin"
              name={t('chart.margin.gross')}
              stroke={COLORS.gross_margin}
              strokeWidth={2}
              fill="url(#grossGradient)"
              dot={{ r: 3, fill: COLORS.gross_margin }}
            />
            <Area
              type="monotone"
              dataKey="ebitda_margin"
              name={t('chart.margin.ebitda')}
              stroke={COLORS.ebitda_margin}
              strokeWidth={2}
              fill="url(#ebitdaGradient)"
              dot={{ r: 3, fill: COLORS.ebitda_margin }}
            />
            <Line
              type="monotone"
              dataKey="operating_margin"
              name={t('chart.margin.operating')}
              stroke={COLORS.operating_margin}
              strokeWidth={2}
              dot={{ r: 3, fill: COLORS.operating_margin }}
              opacity={0.7}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
