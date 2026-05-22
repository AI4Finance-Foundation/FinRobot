// v5 §6.6 历史估值带 — EV/EBITDA + P/FCF time series with P25/P75/P90 bands.
// SVG polyline (no chart lib) so it bundles cleanly without dragging an
// extra dep — the chart is intentionally minimal.

import { useState } from 'react'
import { useHistoricalBand } from '../../hooks/useV5Artifacts'
import type { HistoricalMetric } from '../../types/v5'


const CHART_HEIGHT = 160
const CHART_PAD_X = 24
const CHART_PAD_Y = 12

interface HistoricalBandChartProps {
  ticker: string
}

export function HistoricalBandChart({ ticker }: HistoricalBandChartProps): React.ReactElement {
  const [metric, setMetric] = useState<HistoricalMetric>('ev_ebitda')
  const { data, isLoading, isError } = useHistoricalBand(ticker, metric, 3)

  return (
    <section id="sec-band" className="cosmic-card" style={{ margin: "12px 0" }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📊 历史估值带</h2>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value as HistoricalMetric)}
          style={{
            fontSize: 11,
            padding: '4px 8px',
            border: '1px solid var(--border)',
            borderRadius: 4,
            background: 'transparent',
            color: 'var(--text)',
          }}
        >
          <option value="ev_ebitda">EV / EBITDA</option>
          <option value="p_fcf">P / FCF</option>
        </select>
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>历史估值带加载中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--danger)' }}>历史估值带加载失败</p>
      )}
      {data && data.sample_count > 0 && (
        <>
          <Quantiles data={data} metric={metric} />
          <Timeline points={data.timeline} band={data} />
          <Classification klass={data.classification} />
        </>
      )}
      {data && data.sample_count === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>
          没有足够数据计算历史估值带 — 请确认 EBITDA / FCF 是否在历史财报披露
        </p>
      )}
    </section>
  )
}

interface QuantilesProps {
  data: NonNullable<ReturnType<typeof useHistoricalBand>['data']>
  metric: HistoricalMetric
}

function Quantiles({ data, metric }: QuantilesProps): React.ReactElement {
  const label = metric === 'ev_ebitda' ? 'EV/EBITDA' : 'P/FCF'
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        marginBottom: 12,
        fontSize: 12,
        color: 'var(--text-soft)',
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      <span>
        当前 {label} <strong style={{ fontWeight: 600 }}>{format(data.current)}</strong>
      </span>
      <span>中位 {format(data.median)}</span>
      <span>P25 {format(data.p25)}</span>
      <span>P75 {format(data.p75)}</span>
      <span>P90 {format(data.p90)}</span>
    </div>
  )
}

interface TimelineProps {
  points: { date: string; value: number }[]
  band: {
    p25: number | null
    p75: number | null
    median: number | null
    current: number | null
  }
}

function Timeline({ points, band }: TimelineProps): React.ReactElement {
  if (points.length < 2) {
    return <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>样本太少 — 无法画图</p>
  }
  const values = points.map((p) => p.value)
  const min = Math.min(...values, band.p25 ?? values[0])
  const max = Math.max(...values, band.p75 ?? values[0])
  const rng = max - min || 1
  const width = 720
  const innerW = width - CHART_PAD_X * 2
  const innerH = CHART_HEIGHT - CHART_PAD_Y * 2

  const xy = (i: number, v: number) => {
    const x = CHART_PAD_X + (i / (points.length - 1)) * innerW
    const y = CHART_PAD_Y + (1 - (v - min) / rng) * innerH
    return [x, y] as const
  }

  const path = points
    .map((p, i) => {
      const [x, y] = xy(i, p.value)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const yFor = (v: number | null) => {
    if (v === null) return null
    return CHART_PAD_Y + (1 - (v - min) / rng) * innerH
  }
  const yP25 = yFor(band.p25)
  const yP75 = yFor(band.p75)
  const yMed = yFor(band.median)

  return (
    <svg
      data-testid="historical-band-svg"
      viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
      style={{ width: '100%', height: CHART_HEIGHT, overflow: 'visible' }}
    >
      {/* p25–p75 band */}
      {yP25 !== null && yP75 !== null && (
        <rect
          x={CHART_PAD_X}
          y={Math.min(yP25, yP75)}
          width={innerW}
          height={Math.abs(yP25 - yP75)}
          fill="rgba(16, 185, 129, 0.10)"
        />
      )}
      {/* median line */}
      {yMed !== null && (
        <line
          x1={CHART_PAD_X}
          x2={CHART_PAD_X + innerW}
          y1={yMed}
          y2={yMed}
          stroke="#10B981"
          strokeWidth={1}
          strokeDasharray="4 4"
          opacity={0.6}
        />
      )}
      {/* main series */}
      <path d={path} stroke="#3B82F6" strokeWidth={1.5} fill="none" />
    </svg>
  )
}

function Classification({
  klass,
}: {
  klass: 'expensive' | 'fair' | 'cheap' | 'unknown'
}): React.ReactElement | null {
  if (klass === 'unknown') return null
  const text = {
    expensive: '当前估值偏贵（超 P75 / P90）',
    fair: '当前估值合理（P25 ↔ P75）',
    cheap: '当前估值偏便宜（低于 P25）',
  }[klass]
  const color = klass === 'expensive' ? '#EF4444' : klass === 'cheap' ? '#10B981' : '#F59E0B'
  return (
    <p
      data-testid="historical-band-classification"
      data-class={klass}
      style={{ marginTop: 12, fontSize: 12, color }}
    >
      {text}
    </p>
  )
}

function format(v: number | null): string {
  if (v === null) return 'N/A'
  return v.toFixed(1)
}
