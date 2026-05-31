// PriceTrendChart — readable 1Y price chart for the workspace MarketDataZone.
//
// Replaces the old hand-rolled sparkline that drew only a shape: this one is a
// Recharts area chart you can actually read numbers off — hover for date +
// close (+ OHLC / volume when the provider carries them), a price Y-axis,
// dashed period high/low reference lines, and a current-price dot. Matches the
// house chart conventions (CHART_TOOLTIP tokens + JetBrains Mono) used by the
// statement charts in this directory.
//
// The deeper multi-range / candlestick view belongs in the report's
// "技术与高阶分析" chapter; this card stays a compact dashboard read.

import {
  Area,
  AreaChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PricePoint } from '../../hooks/useTickerData'

interface Props {
  points: PricePoint[] | null
}

const TOOLTIP_STYLE: React.CSSProperties = {
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border-glow)',
  borderRadius: 6,
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '8px 10px',
}

const AXIS_TICK = {
  fill: 'var(--text-muted)',
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
} as const

/** Trim a provider window that overshoots a year down to the last ~365 days.
 *  FMP hands back a cushion; anchoring the change % / chart to points[0] then
 *  measures from ~17 months ago (the TSLA +9.8%-vs-+21% bug). */
function windowOneYear(points: PricePoint[]): PricePoint[] {
  const last = new Date(points[points.length - 1].date)
  const cutoff = new Date(last)
  cutoff.setDate(cutoff.getDate() - 365)
  const startIdx = Math.max(
    0,
    points.findIndex((p) => new Date(p.date) >= cutoff),
  )
  return points.slice(startIdx)
}

function fmtPrice(v: number): string {
  return `$${v.toFixed(2)}`
}

function fmtVol(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return String(v)
}

function fmtAxisDate(d: string): string {
  // YYYY-MM-DD → MM/YY for the X axis (compact, monospace-aligned).
  const [y, m] = d.split('-')
  return m && y ? `${m}/${y.slice(2)}` : d
}

interface TooltipPayloadItem {
  payload: PricePoint
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: TooltipPayloadItem[]
}): React.ReactElement | null {
  if (!active || !payload || payload.length === 0) return null
  const p = payload[0].payload
  const rows: [string, string][] = [['收盘', fmtPrice(p.close)]]
  if (Number.isFinite(p.open) && Number.isFinite(p.high) && Number.isFinite(p.low)) {
    rows.push(['开/高/低', `${fmtPrice(p.open)} / ${fmtPrice(p.high)} / ${fmtPrice(p.low)}`])
  }
  if (Number.isFinite(p.volume) && p.volume > 0) {
    rows.push(['成交量', fmtVol(p.volume)])
  }
  return (
    <div style={TOOLTIP_STYLE}>
      <div style={{ color: 'var(--text-primary)', marginBottom: 4 }}>{p.date}</div>
      {rows.map(([label, value]) => (
        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span style={{ color: 'var(--text-muted)' }}>{label}</span>
          <span style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
            {value}
          </span>
        </div>
      ))}
    </div>
  )
}

export function PriceTrendChart({ points }: Props): React.ReactElement {
  if (!points || points.length < 2) {
    return (
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
        加载中…
      </p>
    )
  }

  const data = windowOneYear(points)
  const closes = data.map((p) => p.close)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const pad = (max - min) * 0.08 || 1
  const last = data[data.length - 1]
  const first = closes[0]
  const pct = ((last.close - first) / first) * 100
  const up = pct >= 0

  const spanDays = Math.round(
    (new Date(last.date).getTime() - new Date(data[0].date).getTime()) / 86_400_000,
  )
  const spanLabel = spanDays >= 350 ? '1Y' : `${spanDays}D`

  return (
    <div>
      <ResponsiveContainer width="100%" height={170}>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="price-trend-grad" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--accent-cyan)" stopOpacity={0.4} />
              <stop offset="100%" stopColor="var(--accent-cyan)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="date"
            tickFormatter={fmtAxisDate}
            tick={AXIS_TICK}
            axisLine={{ stroke: 'var(--border-soft)' }}
            tickLine={false}
            minTickGap={48}
          />
          <YAxis
            orientation="right"
            width={48}
            domain={[min - pad, max + pad]}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            tickCount={4}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--border-glow)' }} />
          <ReferenceLine
            y={max}
            stroke="var(--text-dim)"
            strokeDasharray="3 3"
            label={{
              value: `H ${fmtPrice(max)}`,
              position: 'insideTopLeft',
              fill: 'var(--text-muted)',
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
            }}
          />
          <ReferenceLine
            y={min}
            stroke="var(--text-dim)"
            strokeDasharray="3 3"
            label={{
              value: `L ${fmtPrice(min)}`,
              position: 'insideBottomLeft',
              fill: 'var(--text-muted)',
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
            }}
          />
          <Area
            type="monotone"
            dataKey="close"
            stroke="var(--accent-cyan)"
            strokeWidth={1.6}
            fill="url(#price-trend-grad)"
            dot={false}
            activeDot={{ r: 3, fill: 'var(--accent-cyan)', stroke: 'var(--bg-deep)' }}
            isAnimationActive={false}
          />
          <ReferenceDot
            x={last.date}
            y={last.close}
            r={3.5}
            fill={up ? 'var(--success)' : 'var(--danger)'}
            stroke="var(--bg-deep)"
            strokeWidth={1.5}
          />
        </AreaChart>
      </ResponsiveContainer>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          marginTop: 4,
        }}
      >
        <span>
          {spanLabel} 走势 · 现价 {fmtPrice(last.close)}
        </span>
        <span style={{ color: up ? 'var(--success)' : 'var(--danger)' }}>
          {up ? '+' : ''}
          {pct.toFixed(1)}%
        </span>
      </div>
    </div>
  )
}
