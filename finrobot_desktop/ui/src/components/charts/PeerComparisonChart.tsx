import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'
import { CosmicTooltip, CosmicLegend } from './chartTooltip'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
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

export default function PeerComparisonChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

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
            <Bar dataKey="ev_ebitda" name="EV/EBITDA" fill={PRIMARY} radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`ev-${index}`} fill={entry.is_target ? TARGET_HIGHLIGHT : PRIMARY} />
              ))}
            </Bar>
            <Bar dataKey="pe_ratio" name="P/E Ratio" fill={ACCENT} radius={[3, 3, 0, 0]}>
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
