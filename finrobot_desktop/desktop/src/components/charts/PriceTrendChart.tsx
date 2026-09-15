// PriceTrendChart — readable 1Y price chart for the workspace MarketDataZone.
//
// A Recharts area chart you can read numbers off — hover for date +
// close (+ OHLC / volume when the provider carries them), a price Y-axis,
// and a last-close dot. (No high/low reference lines: the 52W intraday range
// lives in the TechnicalsStrip range bar below — see note at the chart body.)
// Matches the house chart conventions (CHART_TOOLTIP tokens + JetBrains Mono)
// used by the statement charts in this directory.
//
// The deeper multi-range / candlestick view belongs in the report's
// "技术与高阶分析" chapter; this card stays a compact dashboard read.

import { Area, AreaChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PricePoint } from '../../hooks/useTickerData'
import { useI18n } from '../../i18n'
import { SkelBar } from '../Skeleton'
import { CosmicTooltipShell } from './chartTooltip'

interface Props {
  points: PricePoint[] | null
  /** True while the price query is still in flight. Distinguishes "still
   *  loading" from "resolved with no usable history" — without it an empty
   *  payload rendered as a permanent "Loading…". */
  loading?: boolean
  /** Live quote + session state for the right-edge readout. When the session is
   *  live the last daily bar is still forming and its "close" lags this quote, so
   *  the readout shows `currentPrice` (== the header) labeled "Latest" instead of
   *  a misleading "Last close". Omitted ⇒ falls back to the last bar's close. */
  currentPrice?: number | null
  sessionState?: string | null
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
  // Drop EVERY non-finite / non-positive close, not just leading ones: the raw
  // provider fast path (/price route provider-cache) bypasses the backend
  // normalize chokepoint, and yfinance can hand an all-NaN OHLC session row
  // (serialized close:null — crashed the footer's toFixed, 2026-06-11). A 0/null
  // close anywhere skews the Y domain; trailing ones poison the last-close
  // readout and the 1Y change anchor.
  return points.slice(startIdx).filter((p) => Number.isFinite(p.close) && p.close > 0)
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
  const { t } = useI18n()
  if (!active || !payload || payload.length === 0) return null
  const p = payload[0].payload
  const rows: [string, string][] = [[t('chart.priceTrend.close'), fmtPrice(p.close)]]
  if (Number.isFinite(p.open) && Number.isFinite(p.high) && Number.isFinite(p.low)) {
    rows.push([
      t('chart.priceTrend.ohlc'),
      `${fmtPrice(p.open)} / ${fmtPrice(p.high)} / ${fmtPrice(p.low)}`,
    ])
  }
  if (Number.isFinite(p.volume) && p.volume > 0) {
    rows.push([t('chart.priceTrend.volume'), fmtVol(p.volume)])
  }
  // Shares the cosmic tooltip shell, but keeps label/value rows (no series dot)
  // since OHLC/volume aren't colour-coded series.
  return (
    <CosmicTooltipShell label={p.date}>
      {rows.map(([label, value]) => (
        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
          <span style={{ color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
            {value}
          </span>
        </div>
      ))}
    </CosmicTooltipShell>
  )
}

export function PriceTrendChart({
  points,
  loading = false,
  currentPrice,
  sessionState,
}: Props): React.ReactElement {
  const { t } = useI18n()
  // Guard on the FILTERED window, not the raw length — a payload can be
  // non-empty yet all-null closes (windowOneYear drops those).
  const data = points && points.length > 0 ? windowOneYear(points) : []
  if (data.length < 2) {
    // Fixed-height skeleton while the price query is still in flight, sized to
    // the loaded render (170px chart area + the change-readout footer row) so
    // the column doesn't reflow when the chart lands. Only the still-loading
    // case gets it; a resolved-but-empty payload is a terminal "no history"
    // state with nothing to reflow into, so it keeps the plain text line.
    if (loading) {
      return (
        <div
          data-testid="price-trend-skeleton"
          aria-busy="true"
          aria-label={t('chart.priceTrend.loading')}
        >
          <SkelBar height={170} width="100%" />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <SkelBar height={12} width="42%" />
            <SkelBar height={12} width="12%" />
          </div>
        </div>
      )
    }
    return (
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
        {t('chart.priceTrend.empty')}
      </p>
    )
  }

  const closes = data.map((p) => p.close)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const pad = (max - min) * 0.08 || 1
  const last = data[data.length - 1]
  const first = closes[0]
  // During a live session the last daily bar is still forming, and the provider's
  // historical-chart endpoint lags the real-time quote — so its "close" disagrees
  // with the header price (the reported "two different prices"). When live, show
  // the live quote (== header) labeled "Latest"; only call it "Last close" once
  // the session is closed and the bar is a real settled close.
  const live = sessionState === 'live' && typeof currentPrice === 'number'
  const endVal = live ? currentPrice : last.close
  // Guard first===0 (provider halt/sparse day): mirrors the backend prev==0
  // guards (contracts.py trailing_1y_return_pct / routes/data.py:429). null → '—'.
  const pct = first > 0 ? ((endVal - first) / first) * 100 : null
  const up = pct !== null && pct >= 0

  const spanDays = Math.round(
    (new Date(last.date).getTime() - new Date(data[0].date).getTime()) / 86_400_000,
  )
  const spanLabel = spanDays >= 350 ? '1Y' : `${spanDays}D`

  return (
    <div data-testid="price-trend-chart">
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
          {/* No high/low reference lines here on purpose. They marked the
              windowed daily-CLOSE extremes, which read as a second "52W high/low"
              clashing with the TechnicalsStrip range bar below — that bar carries
              the authoritative 52-week INTRADAY range (matching the quote
              snapshot). One high/low caliber on the page, not two. */}
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
          {spanLabel} {t('chart.priceTrend.trend')} ·{' '}
          {t(live ? 'chart.priceTrend.latest' : 'chart.priceTrend.last')} {fmtPrice(endVal)}
        </span>
        <span
          style={{
            color: pct === null ? 'var(--text-muted)' : up ? 'var(--success)' : 'var(--danger)',
          }}
        >
          {pct === null ? '—' : `${up ? '+' : ''}${pct.toFixed(1)}%`}
        </span>
      </div>
    </div>
  )
}
