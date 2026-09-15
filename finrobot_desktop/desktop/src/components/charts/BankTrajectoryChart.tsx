// Bank-caliber trajectory — Revenue + Net Income bars + a Return-on-Equity line.
// Replaces the Revenue&EBITDA + margin charts for balance-sheet financials, where
// EBITDA / EBITDA-margin are a category error. The ROE line renders ONLY when the
// artifact carries per-year shareholders' equity (empty on pre-2026-07-06 runs);
// without it the chart degrades to Revenue + Net Income (never fabricated).

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
import { CosmicLegend, CosmicTooltipShell, CosmicTooltipRow } from './chartTooltip'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const REVENUE_COLOR = 'var(--primary)'
const NET_INCOME_COLOR = 'var(--accent-cyan)'
const ROE_COLOR = 'var(--secondary)'
const AXIS = {
  fill: 'var(--text-secondary)',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
}
const MONEY_LABEL = {
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  fontWeight: 600,
} as const

function money(v: number): string {
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toLocaleString()}`
}
const pct = (v: number): string => `${(v * 100).toFixed(1)}%`
const moneyLabel = (v: unknown): string => (typeof v === 'number' && v > 0 ? money(v) : '')

interface TPayload {
  value?: number | string | null
  name?: string
  dataKey?: string | number
  color?: string
}

// Money bars + a % ROE line share the tooltip, so it formats per-series (the
// single-format CosmicTooltip can't) — composed from the shared shell/row.
function BankTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TPayload[]
  label?: string | number
}) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <CosmicTooltipShell label={label}>
      {payload.map((p) => {
        const v = typeof p.value === 'number' ? p.value : 0
        return (
          <CosmicTooltipRow
            key={String(p.dataKey ?? p.name)}
            color={p.color}
            name={p.name}
            value={p.dataKey === 'roe' ? pct(v) : money(v)}
          />
        )
      })}
    </CosmicTooltipShell>
  )
}

export default function BankTrajectoryChart({ data, title }: ChartProps) {
  const { t, locale } = useI18n()
  if (!data || data.length === 0) return null
  const hasRoe = data.some((d) => typeof d.roe === 'number' && Number.isFinite(d.roe))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} barGap={6} margin={{ top: 24, right: 16, left: 0, bottom: 4 }}>
            <XAxis
              dataKey="year"
              tick={AXIS}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <YAxis
              yAxisId="money"
              tickFormatter={money}
              tick={AXIS}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-soft)' }}
              width={64}
            />
            {hasRoe && (
              <YAxis
                yAxisId="roe"
                orientation="right"
                tickFormatter={(v) => `${Math.round(v * 100)}%`}
                tick={AXIS}
                tickLine={false}
                axisLine={{ stroke: 'var(--border-soft)' }}
                width={46}
              />
            )}
            <Tooltip
              content={<BankTooltip />}
              cursor={{ fill: 'var(--primary-soft)', radius: 4 }}
            />
            <Legend content={<CosmicLegend />} />
            <Bar
              yAxisId="money"
              dataKey="revenue"
              name={t('chart.series.revenue')}
              radius={[4, 4, 0, 0]}
              fill={REVENUE_COLOR}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="revenue"
                position="top"
                formatter={moneyLabel}
                style={{ ...MONEY_LABEL, fill: 'var(--text-primary)' }}
              />
            </Bar>
            <Bar
              yAxisId="money"
              dataKey="net_income"
              name={locale === 'zh' ? '净利润' : 'Net Income'}
              radius={[4, 4, 0, 0]}
              fill={NET_INCOME_COLOR}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="net_income"
                position="top"
                formatter={moneyLabel}
                style={{ ...MONEY_LABEL, fill: 'var(--accent-cyan)' }}
              />
            </Bar>
            {hasRoe && (
              <Line
                yAxisId="roe"
                type="monotone"
                dataKey="roe"
                name="ROE"
                stroke={ROE_COLOR}
                strokeWidth={2}
                dot={{ r: 3, fill: ROE_COLOR }}
                isAnimationActive={false}
                connectNulls
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
