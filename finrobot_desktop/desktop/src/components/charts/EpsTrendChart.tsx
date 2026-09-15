import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  LabelList,
} from 'recharts'
import { useI18n } from '../../i18n'
import { CosmicTooltipShell, CosmicTooltipRow } from './chartTooltip'

interface EpsRow {
  year: string
  eps: number | null
  yoy: number | null
}

interface ChartProps {
  data: EpsRow[]
  title: string
}

const BAR_COLOR = 'var(--primary)'

// Color each EPS bar by its YoY direction (涨绿跌红): growth green, contraction
// red, the baseline year (no prior comparison) neutral. The exact % already
// lives in the tooltip; the per-bar color makes the growth trajectory scannable
// without hovering each bar (the Koyfin convention).
export function epsBarColor(yoy: number | null): string {
  if (yoy == null || !Number.isFinite(yoy)) return BAR_COLOR
  return yoy >= 0 ? 'var(--success)' : 'var(--danger)'
}

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
}

interface TooltipProps {
  active?: boolean
  payload?: { payload: EpsRow }[]
}

function EpsTooltip({ active, payload }: TooltipProps) {
  const { t } = useI18n()
  const row = active ? payload?.[0]?.payload : undefined
  if (!row || row.eps == null) return null
  const yoyColor = row.yoy == null ? undefined : row.yoy >= 0 ? 'var(--success)' : 'var(--danger)'
  return (
    <CosmicTooltipShell label={row.year}>
      <CosmicTooltipRow
        color={BAR_COLOR}
        name={t('chart.epsTrend.eps')}
        value={`$${row.eps.toFixed(2)}`}
      />
      {row.yoy != null && (
        <CosmicTooltipRow
          color={yoyColor}
          name={t('chart.epsTrend.yoy')}
          value={`${row.yoy >= 0 ? '+' : ''}${row.yoy.toFixed(0)}%`}
        />
      )}
    </CosmicTooltipShell>
  )
}

export default function EpsTrendChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 24, right: 12, left: 0, bottom: 4 }}>
            <XAxis
              dataKey="year"
              tick={AXIS_TICK}
              axisLine={{ stroke: 'var(--border-soft)' }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `$${v}`}
              tick={AXIS_TICK}
              axisLine={{ stroke: 'var(--border-soft)' }}
              tickLine={false}
              width={48}
            />
            <Tooltip content={<EpsTooltip />} cursor={{ fill: 'var(--primary-soft)', radius: 4 }} />
            <Bar
              dataKey="eps"
              name="EPS"
              fill={BAR_COLOR}
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            >
              {data.map((row, i) => (
                <Cell key={`eps-${i}`} fill={epsBarColor(row.yoy)} />
              ))}
              <LabelList
                dataKey="eps"
                position="top"
                formatter={(v: unknown) => (typeof v === 'number' ? `$${v.toFixed(2)}` : '')}
                style={{
                  fill: 'var(--text-primary)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  fontWeight: 600,
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
