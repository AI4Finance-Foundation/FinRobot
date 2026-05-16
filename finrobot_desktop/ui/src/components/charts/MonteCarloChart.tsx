import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
  Cell,
} from 'recharts'
import type { TooltipValueType } from 'recharts'
import { useMemo } from 'react'
import type { MonteCarloResult } from '../../stores/appStore'

interface Props {
  result: MonteCarloResult
  currentPrice: number | null
}

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

const BAR_COLOR = '#60A5FA'
const MARKER_COLOR = '#F59E0B'

export default function MonteCarloChart({ result, currentPrice }: Props) {
  const { chartData, p25, p75, median, mean } = useMemo(() => {
    const bins = result.histogram_bins
    const counts = result.histogram_counts

    const data = counts.map((count, i) => ({
      binStart: bins[i],
      binEnd: bins[i + 1] ?? bins[i],
      binMid: (bins[i] + (bins[i + 1] ?? bins[i])) / 2,
      count,
      label: `$${bins[i].toFixed(0)}`,
    }))

    return {
      chartData: data,
      p25: result.percentiles['25'] ?? 0,
      p75: result.percentiles['75'] ?? 0,
      median: result.percentiles['50'] ?? 0,
      mean: result.mean,
    }
  }, [result])

  const pctLabel = currentPrice != null
    ? `Current price ($${currentPrice.toFixed(2)}) is at the ${result.current_price_percentile.toFixed(0)}th percentile`
    : null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Fair Value Distribution</span>
        <span className="card-badge font-mono">
          {result.n_valid.toLocaleString()} sims
        </span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} barCategoryGap={0} barGap={0}>
            <XAxis
              dataKey="binMid"
              tick={{ fill: '#4B5563', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#E2E5EB' }}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis
              tick={{ fill: '#4B5563', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#E2E5EB' }}
              tickFormatter={(v: number) => v.toLocaleString()}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP} labelStyle={{ color: 'var(--text-primary)' }}
              formatter={(value: TooltipValueType | undefined) => {
                const v = typeof value === 'number' ? value : 0
                return [v.toLocaleString(), 'Simulations']
              }}
              labelFormatter={(label: unknown) => {
                const n = typeof label === 'number' ? label : Number(label)
                return `$${n.toFixed(2)}`
              }}
            />

            {/* 25-75 percentile shaded region */}
            <ReferenceArea
              x1={p25}
              x2={p75}
              fill="rgba(96, 165, 250, 0.08)"
              strokeOpacity={0}
            />

            {/* Current price marker (dashed) */}
            {currentPrice != null && (
              <ReferenceLine
                x={currentPrice}
                stroke={MARKER_COLOR}
                strokeWidth={1.5}
                strokeDasharray="6 3"
                label={{
                  value: `Current $${currentPrice.toFixed(0)}`,
                  position: 'top',
                  fill: MARKER_COLOR,
                  fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              />
            )}

            {/* Median line (dark solid on light bg) */}
            <ReferenceLine
              x={median}
              stroke="#111827"
              strokeWidth={1.5}
              label={{
                value: `Median $${median.toFixed(0)}`,
                position: 'insideTopRight',
                fill: '#111827',
                fontSize: 10,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            />

            {/* Mean line (blue dashed) */}
            <ReferenceLine
              x={mean}
              stroke="#60A5FA"
              strokeWidth={1}
              strokeDasharray="4 2"
            />

            <Bar dataKey="count" radius={[2, 2, 0, 0]}>
              {chartData.map((entry, index) => {
                const inRange = entry.binMid >= p25 && entry.binMid <= p75
                return (
                  <Cell
                    key={`mc-${index}`}
                    fill={inRange ? BAR_COLOR : `${BAR_COLOR}66`}
                  />
                )
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        {/* Percentile table */}
        <div className="mc-percentile-table">
          <table>
            <thead>
              <tr>
                <th>5th</th>
                <th>25th</th>
                <th>50th</th>
                <th>75th</th>
                <th>95th</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="font-mono">${(result.percentiles['5'] ?? 0).toFixed(2)}</td>
                <td className="font-mono">${(result.percentiles['25'] ?? 0).toFixed(2)}</td>
                <td className="font-mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                  ${(result.percentiles['50'] ?? 0).toFixed(2)}
                </td>
                <td className="font-mono">${(result.percentiles['75'] ?? 0).toFixed(2)}</td>
                <td className="font-mono">${(result.percentiles['95'] ?? 0).toFixed(2)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Current price percentile callout */}
        {pctLabel && (
          <div className="mc-callout">
            {pctLabel}
          </div>
        )}

        {/* Stats row */}
        <div className="mc-stats">
          <span className="font-mono">Mean: ${result.mean.toFixed(2)}</span>
          <span className="mc-stats-sep" />
          <span className="font-mono">Std: ${result.std.toFixed(2)}</span>
          <span className="mc-stats-sep" />
          <span className="font-mono">Valid: {result.n_valid.toLocaleString()}/{(result.assumptions_used['n_simulations'] ?? 10000).toLocaleString()}</span>
        </div>
      </div>
    </div>
  )
}
