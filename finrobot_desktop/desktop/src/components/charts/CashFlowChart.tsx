import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  LabelList,
} from 'recharts'
import { useI18n } from '../../i18n'
import { CosmicTooltip, CosmicLegend } from './chartTooltip'

interface ChartProps {
  data: { year: string; operating: number; investing: number; financing: number }[]
  title: string
}

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
}

// Currency-compact formatter shared by the Y-axis ticks, the tooltip, and the
// bar-top value labels so all three read identically (cash-flow values are
// large currency magnitudes — never multiples, so no "x" suffix).
export function formatBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return String(v)
}

// Bar-top value label: only render a non-zero magnitude (a $0 component bar
// would otherwise stamp a "0" on the axis line). Mirrors EpsTrendChart's mono
// LabelList styling, sized down a notch for the 3-series cluster density.
const LABEL_STYLE = {
  fill: 'var(--text-secondary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 9,
  fontWeight: 600,
} as const

export function barLabel(v: unknown): string {
  return typeof v === 'number' && v !== 0 ? formatBillions(v) : ''
}

export default function CashFlowChart({ data, title }: ChartProps) {
  const { t } = useI18n()
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
            <XAxis dataKey="year" tick={AXIS_TICK} axisLine={{ stroke: 'var(--border-soft)' }} />
            <YAxis
              tickFormatter={formatBillions}
              tick={AXIS_TICK}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <Tooltip
              content={<CosmicTooltip format={formatBillions} />}
              cursor={{ fill: 'var(--primary-soft)', radius: 4 }}
            />
            <Legend content={<CosmicLegend />} />
            <Bar
              dataKey="operating"
              name={t('chart.cashflow.operating')}
              fill="var(--success)"
              radius={[2, 2, 0, 0]}
            >
              <LabelList
                dataKey="operating"
                position="top"
                formatter={barLabel}
                style={LABEL_STYLE}
              />
            </Bar>
            <Bar
              dataKey="investing"
              name={t('chart.cashflow.investing')}
              fill="var(--danger)"
              radius={[2, 2, 0, 0]}
            >
              <LabelList
                dataKey="investing"
                position="top"
                formatter={barLabel}
                style={LABEL_STYLE}
              />
            </Bar>
            <Bar
              dataKey="financing"
              name={t('chart.cashflow.financing')}
              fill="var(--chart-gold)"
              radius={[2, 2, 0, 0]}
            >
              <LabelList
                dataKey="financing"
                position="top"
                formatter={barLabel}
                style={LABEL_STYLE}
              />
            </Bar>
            <Line
              type="monotone"
              dataKey="net"
              name={t('chart.cashflow.net')}
              stroke="var(--primary)"
              strokeWidth={2}
              dot={{ r: 3, fill: 'var(--primary)' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
