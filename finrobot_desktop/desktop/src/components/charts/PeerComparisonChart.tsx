import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  LabelList,
} from 'recharts'
import { useI18n } from '../../i18n'
import { CosmicTooltip, CosmicLegend } from './chartTooltip'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
  // Primary (first) bar series. Defaults to EV/EBITDA; balance-sheet financials
  // pass pb_ratio / "P/B" since EV/EBITDA is a category error for them.
  primaryKey?: string
  primaryName?: string
}

// Design system chart palette
const PRIMARY = 'var(--primary)' // chart-1, EV/EBITDA series
const ACCENT = 'var(--chart-gold)' // P/E series — gold, not green, to avoid "up" connotation
const TARGET_HIGHLIGHT = 'var(--warning)' // target ticker highlight

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
}

// These bars plot valuation MULTIPLES, so labels carry the "x" suffix (e.g.
// "22.5x") — matching the tooltip's `${v.toFixed(1)}x`. NEVER currency here.
// With ~6 tickers × 2 series the cluster is dense, so only the PRIMARY series
// (EV/EBITDA) gets a bar-top label; the P/E values stay tooltip-only to avoid
// overlapping labels. Matches EpsTrendChart's mono LabelList styling.
const LABEL_STYLE = {
  fill: 'var(--text-secondary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 9,
  fontWeight: 600,
} as const

export function multipleLabel(v: unknown): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(1)}x` : ''
}

export default function PeerComparisonChart({
  data,
  title,
  primaryKey = 'ev_ebitda',
  primaryName,
}: ChartProps) {
  const { t } = useI18n()
  if (!data || data.length === 0) return null
  const primaryLabel = primaryName ?? t('chart.peer.evEbitda')

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} barGap={2}>
            <XAxis dataKey="ticker" tick={AXIS_TICK} axisLine={{ stroke: 'var(--border-soft)' }} />
            <YAxis tick={AXIS_TICK} axisLine={{ stroke: 'var(--border-soft)' }} />
            <Tooltip
              content={<CosmicTooltip format={(v) => `${v.toFixed(1)}x`} />}
              cursor={false}
            />
            <Legend content={<CosmicLegend />} />
            {/* fill on <Bar> drives the legend swatch; <Cell> overrides per-bar
                so the target ticker can be highlighted. Without Bar fill the
                legend icons render black (Recharts default). */}
            <Bar dataKey={primaryKey} name={primaryLabel} fill={PRIMARY} radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`ev-${index}`} fill={entry.is_target ? TARGET_HIGHLIGHT : PRIMARY} />
              ))}
              <LabelList
                dataKey={primaryKey}
                position="top"
                formatter={multipleLabel}
                style={LABEL_STYLE}
              />
            </Bar>
            <Bar dataKey="pe_ratio" name={t('chart.peer.pe')} fill={ACCENT} radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`pe-${index}`} fill={entry.is_target ? TARGET_HIGHLIGHT : ACCENT} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
