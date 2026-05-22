import { useMemo } from 'react'
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import type { LegendPayload } from 'recharts/types/component/DefaultLegendContent'
import type { BollingerPoint } from './technicalUtils'
import { sma, bollingerBands } from './technicalUtils'

// ---------- Types ----------

export interface OHLCRow {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface CandlestickChartProps {
  data: OHLCRow[]
  showSMA20: boolean
  showSMA50: boolean
  showBollinger: boolean
}

// ---------- Design tokens (matches App.css design system) ----------

const UP_COLOR = 'var(--success)'   // --positive
const DOWN_COLOR = 'var(--danger)' // --negative
const SMA20_COLOR = 'var(--secondary)' // --chart-4
const SMA50_COLOR = 'var(--warning)' // --chart-5
const BB_STROKE = 'var(--primary)'

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
}

// ---------- Helpers ----------

function formatVolume(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return String(value)
}

interface CandleRow extends OHLCRow {
  /** [low, high] range for the Bar — gives us the full wick extent */
  _range: [number, number]
  _sma20: number | null
  _sma50: number | null
  _bbUpper: number | null
  _bbLower: number | null
  _bbMiddle: number | null
}

// ---------- Custom candlestick shape for Bar ----------

/**
 * Recharts Bar with a [low, high] range dataKey gives us:
 * - x, y: top-left of the bar (at high price)
 * - width: bar width
 * - height: bar height (from high to low in pixels, positive downward)
 * - payload: full CandleRow with OHLC data
 *
 * We use these to derive pixel positions for the body and wicks.
 */
interface CandleShapeProps {
  x?: number
  y?: number
  width?: number
  height?: number
  payload?: CandleRow
}

function CandleShape(props: CandleShapeProps) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = props
  if (!payload || height === 0) return null

  const { open, close, high, low } = payload
  const isUp = close >= open
  const color = isUp ? UP_COLOR : DOWN_COLOR

  // The bar occupies [high, low] in price space, mapped to [y, y+height] in pixels.
  // pixelPerPrice converts a price delta to a pixel delta.
  const priceRange = high - low
  if (priceRange === 0) return null
  const pxPerPrice = height / priceRange

  // Convert OHLC prices to pixel Y offsets from the bar top (y)
  const bodyTop = y + (high - Math.max(open, close)) * pxPerPrice
  const bodyBottom = y + (high - Math.min(open, close)) * pxPerPrice
  const bodyHeight = Math.max(bodyBottom - bodyTop, 1)

  const centerX = x + width / 2
  const candleWidth = Math.max(3, Math.min(8, width * 0.8))
  const halfCandle = candleWidth / 2

  return (
    <g>
      {/* Upper wick: from high to max(open, close) */}
      <line
        x1={centerX}
        y1={y}
        x2={centerX}
        y2={bodyTop}
        stroke={color}
        strokeWidth={1}
      />
      {/* Lower wick: from min(open, close) to low */}
      <line
        x1={centerX}
        y1={bodyBottom}
        x2={centerX}
        y2={y + height}
        stroke={color}
        strokeWidth={1}
      />
      {/* Candle body */}
      <rect
        x={centerX - halfCandle}
        y={bodyTop}
        width={candleWidth}
        height={bodyHeight}
        fill={color}
        fillOpacity={isUp ? 0.25 : 0.7}
        stroke={color}
        strokeWidth={1}
      />
    </g>
  )
}

// ---------- Custom tooltip ----------

interface TooltipPayloadItem {
  name?: string
  dataKey?: string
  value?: number | number[]
  payload?: CandleRow
  color?: string
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string
}

function OHLCTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const row = payload[0]?.payload
  if (!row) return null
  const isUp = row.close >= row.open
  const changeAbs = row.close - row.open
  const changePct = row.open !== 0 ? (changeAbs / row.open) * 100 : 0

  return (
    <div style={CHART_TOOLTIP}>
      <div style={{ marginBottom: 4, fontWeight: 600 }}>{row.date}</div>
      <div>O: <span style={{ color: 'var(--text-primary)' }}>${row.open.toFixed(2)}</span></div>
      <div>H: <span style={{ color: 'var(--text-primary)' }}>${row.high.toFixed(2)}</span></div>
      <div>L: <span style={{ color: 'var(--text-primary)' }}>${row.low.toFixed(2)}</span></div>
      <div>C: <span style={{ color: 'var(--text-primary)' }}>${row.close.toFixed(2)}</span></div>
      <div style={{ color: isUp ? UP_COLOR : DOWN_COLOR }}>
        {isUp ? '+' : ''}{changeAbs.toFixed(2)} ({isUp ? '+' : ''}{changePct.toFixed(2)}%)
      </div>
      <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>
        Vol: {formatVolume(row.volume)}
      </div>
    </div>
  )
}

// ---------- Main component ----------

export default function CandlestickChart({
  data,
  showSMA20,
  showSMA50,
  showBollinger,
}: CandlestickChartProps) {
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return []

    const closes = data.map((d) => d.close)
    const sma20Values = sma(closes, 20)
    const sma50Values = sma(closes, 50)
    const bb: BollingerPoint[] = bollingerBands(closes, 20, 2)

    return data.map((row, i): CandleRow => ({
      ...row,
      _range: [row.low, row.high],
      _sma20: sma20Values[i],
      _sma50: sma50Values[i],
      _bbUpper: bb[i].upper,
      _bbLower: bb[i].lower,
      _bbMiddle: bb[i].middle,
    }))
  }, [data])

  if (chartData.length === 0) return null

  // Compute price domain with padding
  const allPrices = data.flatMap((d) => [d.high, d.low])
  const minPrice = Math.min(...allPrices)
  const maxPrice = Math.max(...allPrices)
  const pricePad = (maxPrice - minPrice) * 0.05
  const priceDomain: [number, number] = [
    Math.floor(minPrice - pricePad),
    Math.ceil(maxPrice + pricePad),
  ]

  // Max volume -- scale domain so volume bars occupy ~20% of chart height
  const maxVol = Math.max(...data.map((d) => d.volume))

  return (
    <ResponsiveContainer width="100%" height={340}>
      <ComposedChart
        data={chartData}
        margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
      >
        <XAxis
          dataKey="date"
          tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
          axisLine={{ stroke: 'var(--border-soft)' }}
          tickFormatter={(d: string) => {
            const date = new Date(d)
            return `${date.getFullYear().toString().slice(2)}/${(date.getMonth() + 1)
              .toString()
              .padStart(2, '0')}`
          }}
          minTickGap={40}
        />

        {/* Price axis (left) */}
        <YAxis
          yAxisId="price"
          orientation="left"
          domain={priceDomain}
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
          axisLine={{ stroke: 'var(--border-soft)' }}
          tickFormatter={(v: number) => `$${v}`}
        />

        {/* Volume axis (right, hidden -- domain x5 so bars are ~20% height) */}
        <YAxis
          yAxisId="volume"
          orientation="right"
          domain={[0, maxVol * 5]}
          tick={false}
          axisLine={false}
          width={0}
        />

        <Tooltip content={<OHLCTooltip />} />

        {/* Volume bars at bottom */}
        <Bar
          yAxisId="volume"
          dataKey="volume"
          barSize={Math.max(2, Math.min(6, 600 / chartData.length))}
          isAnimationActive={false}
        >
          {chartData.map((entry, idx) => (
            <Cell
              key={idx}
              fill={entry.close >= entry.open ? UP_COLOR : DOWN_COLOR}
              fillOpacity={0.2}
            />
          ))}
        </Bar>

        {/* Bollinger Bands */}
        {showBollinger && (
          <>
            <Line
              yAxisId="price"
              dataKey="_bbUpper"
              stroke={BB_STROKE}
              strokeWidth={1}
              strokeOpacity={0.5}
              dot={false}
              isAnimationActive={false}
              connectNulls
              legendType="none"
            />
            <Line
              yAxisId="price"
              dataKey="_bbLower"
              stroke={BB_STROKE}
              strokeWidth={1}
              strokeOpacity={0.5}
              dot={false}
              isAnimationActive={false}
              connectNulls
              legendType="none"
            />
            <Line
              yAxisId="price"
              dataKey="_bbMiddle"
              stroke={BB_STROKE}
              strokeWidth={1}
              strokeDasharray="4 4"
              strokeOpacity={0.4}
              dot={false}
              isAnimationActive={false}
              connectNulls
              name="BB(20,2)"
            />
          </>
        )}

        {/* SMA overlays */}
        {showSMA20 && (
          <Line
            yAxisId="price"
            dataKey="_sma20"
            stroke={SMA20_COLOR}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
            connectNulls
            name="SMA(20)"
          />
        )}
        {showSMA50 && (
          <Line
            yAxisId="price"
            dataKey="_sma50"
            stroke={SMA50_COLOR}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
            connectNulls
            name="SMA(50)"
          />
        )}

        {/* Candlestick bodies + wicks: Bar with [low, high] range + custom shape */}
        <Bar
          yAxisId="price"
          dataKey="_range"
          barSize={Math.max(4, Math.min(10, 900 / chartData.length))}
          shape={<CandleShape />}
          isAnimationActive={false}
          legendType="none"
        />

        {/* Legend -- only show active overlays */}
        <Legend
          wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}
          content={() => {
            const items: LegendPayload[] = [
              ...(showSMA20
                ? [{ value: 'SMA(20)', type: 'line' as const, color: SMA20_COLOR }]
                : []),
              ...(showSMA50
                ? [{ value: 'SMA(50)', type: 'line' as const, color: SMA50_COLOR }]
                : []),
              ...(showBollinger
                ? [{ value: 'BB(20,2)', type: 'line' as const, color: BB_STROKE }]
                : []),
            ]
            if (items.length === 0) return null
            return (
              <ul style={{ display: 'flex', gap: 12, listStyle: 'none', margin: 0, padding: 0 }}>
                {items.map((item) => (
                  <li
                    key={item.value}
                    style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-secondary)', fontSize: '0.72rem' }}
                  >
                    <svg width="14" height="4">
                      <line x1="0" y1="2" x2="14" y2="2" stroke={item.color} strokeWidth="2" />
                    </svg>
                    {item.value}
                  </li>
                ))}
              </ul>
            )
          }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
