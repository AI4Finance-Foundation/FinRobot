// Chapter 09 — Technical & Advanced Analysis. Live price chip plus three
// quant overlays baked into the equity_research artifact:
//   - Monte Carlo distribution (inline SVG histogram + percentile markers)
//   - Sniper levels (KvGrid of buy/stop/target + R/R)
//   - Historical EV/EBITDA bands (inline SVG timeline + P25/median/P75/P90)

import { Chapter, KvGrid, SubChapter } from './ChapterBase'
import { useTickerPrice, useTickerFinancials } from '../../../hooks/useTickerData'
import type {
  HistoricalBandShape,
  MonteCarloShape,
  SniperShape,
  TechnicalAnalysisShape,
} from './types'

interface ChapterTechnicalProps {
  ticker: string
  technical: TechnicalAnalysisShape | null
}

export function ChapterTechnical({ ticker, technical }: ChapterTechnicalProps): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const { data: fin } = useTickerFinancials(ticker)
  const current = price?.current_price ?? null
  const changePct = price?.change_pct ?? null
  const high52 = fin?.market?.price_52w_high ?? null
  const low52 = fin?.market?.price_52w_low ?? null
  const beta = fin?.market?.beta ?? null
  const range52Position =
    current !== null && high52 !== null && low52 !== null && high52 > low52
      ? ((current - low52) / (high52 - low52)) * 100
      : null

  const cells = [
    current !== null && {
      label: 'Current Price',
      value: `$${current.toFixed(2)}`,
      tone: typeof changePct === 'number' && changePct >= 0 ? ('up' as const) : ('down' as const),
      delta:
        typeof changePct === 'number'
          ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%`
          : undefined,
    },
    low52 !== null && { label: '52W Low', value: `$${low52.toFixed(2)}` },
    high52 !== null && { label: '52W High', value: `$${high52.toFixed(2)}` },
    range52Position !== null && {
      label: '52W Position',
      value: `${range52Position.toFixed(0)}%`,
      delta: range52Position >= 80 ? 'near high' : range52Position <= 20 ? 'near low' : 'mid-range',
    },
    beta !== null && { label: 'Beta (5Y)', value: beta.toFixed(2), delta: 'vs SPX' },
  ].filter(
    (c): c is { label: string; value: string; delta?: string; tone?: 'up' | 'down' } => c !== false,
  )

  const mc = technical?.monte_carlo ?? null
  const sniper = technical?.sniper ?? null
  const bands = technical?.historical_bands ?? null
  const anyOverlay = mc !== null || sniper !== null || bands !== null

  return (
    <Chapter id="technical">
      {cells.length > 0 ? (
        <KvGrid cells={cells} columns={4} />
      ) : (
        <p style={mutedNote}>价格数据暂不可用，请检查代码是否有效或稍后重试</p>
      )}

      {!anyOverlay && (
        <p style={mutedNote} data-testid="technical-cold-state">
          量化叠加层尚未生成 · 重跑 research 后将显示蒙特卡洛分布 / 狙击位 / 历史估值带
        </p>
      )}

      {mc !== null && (
        <SubChapter heading="Monte Carlo Distribution">
          <MonteCarloPanel mc={mc} current={current} />
        </SubChapter>
      )}

      {sniper !== null && (
        <SubChapter heading="Support / Resistance Levels">
          <SniperPanel sniper={sniper} />
        </SubChapter>
      )}

      {bands !== null && (
        <SubChapter heading="Historical EV/EBITDA Bands">
          <HistoricalBandPanel band={bands} />
        </SubChapter>
      )}
    </Chapter>
  )
}

// ---------------------------------------------------------------------------
// Monte Carlo: histogram + percentile markers + current-price reference line
// ---------------------------------------------------------------------------

function MonteCarloPanel({
  mc,
  current,
}: {
  mc: MonteCarloShape
  current: number | null
}): React.ReactElement {
  const bins = mc.histogram_bins ?? []
  const counts = mc.histogram_counts ?? []
  const percentiles = mc.percentiles ?? {}
  const mean = mc.mean
  const std = mc.std
  const pctCurrent = mc.current_price_percentile
  const n = mc.n_valid

  const minPrice = bins.length > 0 ? bins[0] : 0
  const maxPrice = bins.length > 0 ? bins[bins.length - 1] : 0
  const maxCount = counts.length > 0 ? Math.max(...counts) : 1
  const width = 720
  const height = 220
  const padX = 36
  const padY = 24
  const innerW = width - padX * 2
  const innerH = height - padY * 2

  const xScale = (p: number): number =>
    maxPrice > minPrice ? padX + ((p - minPrice) / (maxPrice - minPrice)) * innerW : padX

  return (
    <div>
      <div style={statRow}>
        <Stat label="Mean" value={mean !== undefined ? `$${mean.toFixed(2)}` : '—'} />
        <Stat label="Std Dev" value={std !== undefined ? `$${std.toFixed(2)}` : '—'} />
        <Stat
          label="P5"
          value={percentiles['5'] !== undefined ? `$${percentiles['5'].toFixed(2)}` : '—'}
        />
        <Stat
          label="P50"
          value={percentiles['50'] !== undefined ? `$${percentiles['50'].toFixed(2)}` : '—'}
        />
        <Stat
          label="P95"
          value={percentiles['95'] !== undefined ? `$${percentiles['95'].toFixed(2)}` : '—'}
        />
        <Stat
          label="Current Pct"
          value={pctCurrent !== undefined ? `${pctCurrent.toFixed(0)}th` : '—'}
        />
        <Stat label="Sims" value={n !== undefined ? n.toLocaleString() : '—'} />
      </div>

      {bins.length > 1 && counts.length > 0 && (
        <svg
          role="img"
          aria-label="Monte Carlo implied price distribution"
          data-testid="mc-histogram"
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: '100%', height: 'auto', display: 'block', marginTop: 12 }}
        >
          {counts.map((c, i) => {
            const x0 = xScale(bins[i])
            const x1 = xScale(bins[i + 1])
            const h = (c / maxCount) * innerH
            return (
              <rect
                key={i}
                x={x0}
                y={padY + innerH - h}
                width={Math.max(1, x1 - x0 - 1)}
                height={h}
                fill="var(--secondary)"
                opacity={0.55}
              />
            )
          })}
          {percentiles['5'] !== undefined && (
            <Marker
              x={xScale(percentiles['5'])}
              label="P5"
              color="var(--warning)"
              height={innerH}
              padY={padY}
            />
          )}
          {percentiles['50'] !== undefined && (
            <Marker
              x={xScale(percentiles['50'])}
              label="P50"
              color="var(--accent-cyan)"
              height={innerH}
              padY={padY}
            />
          )}
          {percentiles['95'] !== undefined && (
            <Marker
              x={xScale(percentiles['95'])}
              label="P95"
              color="var(--warning)"
              height={innerH}
              padY={padY}
            />
          )}
          {current !== null && current >= minPrice && current <= maxPrice && (
            <Marker
              x={xScale(current)}
              label="Current"
              color="var(--success)"
              height={innerH}
              padY={padY}
            />
          )}
        </svg>
      )}
    </div>
  )
}

function Marker({
  x,
  label,
  color,
  height,
  padY,
}: {
  x: number
  label: string
  color: string
  height: number
  padY: number
}): React.ReactElement {
  return (
    <g>
      <line
        x1={x}
        x2={x}
        y1={padY}
        y2={padY + height}
        stroke={color}
        strokeWidth={1.5}
        strokeDasharray="4 3"
      />
      <text
        x={x}
        y={padY - 6}
        textAnchor="middle"
        fontFamily="var(--font-mono)"
        fontSize={10}
        fill={color}
      >
        {label}
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Sniper: deterministic price levels — buy / stop / target + R/R
// ---------------------------------------------------------------------------

function SniperPanel({ sniper }: { sniper: SniperShape }): React.ReactElement {
  type Cell = { label: string; value: string; delta?: string; tone?: 'up' | 'down' }
  const cells: Cell[] = []

  if (sniper.ideal_buy !== undefined) {
    cells.push({
      label: 'Ideal Buy',
      value: `$${sniper.ideal_buy.toFixed(2)}`,
      tone: 'up',
      delta:
        sniper.safety_margin !== undefined
          ? `safety ${(sniper.safety_margin * 100).toFixed(0)}%`
          : undefined,
    })
  }
  if (sniper.secondary_buy !== undefined) {
    cells.push({
      label: 'Secondary Buy',
      value: `$${sniper.secondary_buy.toFixed(2)}`,
      delta: 'at support',
    })
  }
  if (sniper.stop_loss !== undefined) {
    cells.push({
      label: 'Stop Loss',
      value: `$${sniper.stop_loss.toFixed(2)}`,
      tone: 'down',
    })
  }
  if (sniper.take_profit !== undefined) {
    cells.push({
      label: 'Take Profit',
      value: `$${sniper.take_profit.toFixed(2)}`,
      tone: 'up',
      delta: 'DCF target',
    })
  }
  if (sniper.support_level !== undefined) {
    cells.push({
      label: 'Support (20d)',
      value: `$${sniper.support_level.toFixed(2)}`,
    })
  }
  if (sniper.resistance_level !== undefined) {
    cells.push({
      label: 'Resistance (20d)',
      value: `$${sniper.resistance_level.toFixed(2)}`,
    })
  }
  if (sniper.risk_reward_ratio !== undefined) {
    const rr = sniper.risk_reward_ratio
    cells.push({
      label: 'R / R Ratio',
      value: rr.toFixed(2),
      tone: rr >= 2 ? 'up' : rr >= 1 ? undefined : 'down',
    })
  }
  if (sniper.position_size_pct !== undefined) {
    cells.push({
      label: 'Suggested Size',
      value: `${sniper.position_size_pct.toFixed(1)}%`,
      delta: 'of portfolio',
    })
  }

  return <KvGrid cells={cells} columns={4} />
}

// ---------------------------------------------------------------------------
// Historical EV/EBITDA bands: timeline + P25 / median / P75 / P90 bands
// ---------------------------------------------------------------------------

const CLASSIFICATION_COLORS: Record<string, string> = {
  expensive: 'var(--danger)',
  fair: 'var(--accent-cyan)',
  cheap: 'var(--success)',
  unknown: 'var(--text-muted)',
}

function HistoricalBandPanel({ band }: { band: HistoricalBandShape }): React.ReactElement {
  const timeline = band.timeline ?? []
  const cls = band.classification ?? 'unknown'
  const color = CLASSIFICATION_COLORS[cls] ?? 'var(--text-muted)'

  const width = 720
  const height = 220
  const padX = 44
  const padY = 24
  const innerW = width - padX * 2
  const innerH = height - padY * 2

  const values = timeline.map(([, v]) => v)
  const minVal =
    values.length > 0 ? Math.min(...values, band.p25 ?? Infinity, band.median ?? Infinity) : 0
  const maxVal =
    values.length > 0
      ? Math.max(...values, band.p75 ?? -Infinity, band.p90 ?? -Infinity, band.current ?? -Infinity)
      : 0
  const spanV = maxVal - minVal || 1

  const yScale = (v: number): number => padY + innerH - ((v - minVal) / spanV) * innerH
  const xScale = (i: number): number =>
    timeline.length > 1 ? padX + (i / (timeline.length - 1)) * innerW : padX

  const path = timeline
    .map(([, v], i) => `${i === 0 ? 'M' : 'L'}${xScale(i)},${yScale(v)}`)
    .join(' ')

  return (
    <div>
      <div style={{ ...statRow, alignItems: 'center' }}>
        <Stat
          label="Current"
          value={
            band.current !== undefined && band.current !== null
              ? `${band.current.toFixed(1)}x`
              : '—'
          }
        />
        <Stat
          label="Median"
          value={
            band.median !== undefined && band.median !== null ? `${band.median.toFixed(1)}x` : '—'
          }
        />
        <Stat
          label="P25"
          value={band.p25 !== undefined && band.p25 !== null ? `${band.p25.toFixed(1)}x` : '—'}
        />
        <Stat
          label="P75"
          value={band.p75 !== undefined && band.p75 !== null ? `${band.p75.toFixed(1)}x` : '—'}
        />
        <Stat
          label="P90"
          value={band.p90 !== undefined && band.p90 !== null ? `${band.p90.toFixed(1)}x` : '—'}
        />
        <span
          data-testid="band-classification"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            padding: '4px 10px',
            borderRadius: 3,
            border: `1px solid ${color}`,
            color,
            marginLeft: 'auto',
          }}
        >
          {cls}
        </span>
      </div>

      {timeline.length > 1 && (
        <svg
          role="img"
          aria-label="Historical EV/EBITDA timeline"
          data-testid="band-timeline"
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: '100%', height: 'auto', display: 'block', marginTop: 12 }}
        >
          {band.p90 !== undefined && band.p90 !== null && (
            <BandLine
              y={yScale(band.p90)}
              label="P90"
              color="var(--warning)"
              width={width}
              padX={padX}
            />
          )}
          {band.p75 !== undefined && band.p75 !== null && (
            <BandLine
              y={yScale(band.p75)}
              label="P75"
              color="var(--secondary)"
              width={width}
              padX={padX}
            />
          )}
          {band.median !== undefined && band.median !== null && (
            <BandLine
              y={yScale(band.median)}
              label="Median"
              color="var(--accent-cyan)"
              width={width}
              padX={padX}
            />
          )}
          {band.p25 !== undefined && band.p25 !== null && (
            <BandLine
              y={yScale(band.p25)}
              label="P25"
              color="var(--success)"
              width={width}
              padX={padX}
            />
          )}
          <path d={path} stroke="var(--text-primary)" strokeWidth={1.5} fill="none" />
          {band.current !== undefined && band.current !== null && timeline.length > 0 && (
            <circle cx={xScale(timeline.length - 1)} cy={yScale(band.current)} r={5} fill={color} />
          )}
        </svg>
      )}
    </div>
  )
}

function BandLine({
  y,
  label,
  color,
  width,
  padX,
}: {
  y: number
  label: string
  color: string
  width: number
  padX: number
}): React.ReactElement {
  return (
    <g>
      <line
        x1={padX}
        x2={width - padX}
        y1={y}
        y2={y}
        stroke={color}
        strokeWidth={1}
        strokeDasharray="3 3"
        opacity={0.7}
      />
      <text x={width - padX + 4} y={y + 3} fontFamily="var(--font-mono)" fontSize={10} fill={color}>
        {label}
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Shared inline atoms
// ---------------------------------------------------------------------------

function Stat({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-muted)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          color: 'var(--text-primary)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
    </div>
  )
}

const statRow: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 18,
  alignItems: 'flex-end',
  margin: '4px 0 8px',
}

const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'rgba(15, 15, 34, 0.5)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
