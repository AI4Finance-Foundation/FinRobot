import { useMemo } from 'react'

import { useI18n } from '../../i18n'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

// The 8 heatmap tiers, ordered HIGH implied value → LOW. These are the exact
// `hm-*` cell backgrounds (App.css): hm-5 = --legacy-green-30 (the most green,
// = highest implied price via heatmapClass mapping normalised≥0.9), down to
// hm--2 = --legacy-red-25 (the most red, = lowest implied price). The legend
// therefore reads green = higher implied value, red = lower implied value.
const LEGEND_RAMP = [
  'var(--legacy-green-30)',
  'var(--legacy-green-18)',
  'var(--legacy-green-08)',
  'var(--legacy-amber-06)',
  'var(--legacy-amber-12)',
  'var(--legacy-red-08)',
  'var(--legacy-red-15)',
  'var(--legacy-red-25)',
] as const

/**
 * Map normalised value [0, 1] to heatmap CSS class.
 */
function heatmapClass(normalised: number): string {
  if (normalised >= 0.9) return 'hm-5'
  if (normalised >= 0.75) return 'hm-4'
  if (normalised >= 0.6) return 'hm-3'
  if (normalised >= 0.5) return 'hm-2'
  if (normalised >= 0.4) return 'hm-1'
  if (normalised >= 0.25) return 'hm-0'
  if (normalised >= 0.1) return 'hm--1'
  return 'hm--2'
}

interface GridCell {
  wacc: number
  tg: number
  price: number
}

export default function SensitivityHeatmap({ data, title }: ChartProps) {
  const { t } = useI18n()
  const memo = useMemo(() => {
    if (!data || data.length === 0) return null
    const cells: GridCell[] = data.map((d) => ({
      wacc: Number(d.wacc),
      tg: Number(d.tg),
      price: Number(d.implied_price),
    }))

    const waccSet = [...new Set(cells.map((c) => c.wacc))].sort((a, b) => a - b)
    const tgSet = [...new Set(cells.map((c) => c.tg))].sort((a, b) => a - b)

    const lookup = new Map<string, number>()
    for (const c of cells) {
      lookup.set(`${c.wacc}_${c.tg}`, c.price)
    }

    const prices = cells.map((c) => c.price)
    return {
      waccValues: waccSet,
      tgValues: tgSet,
      grid: lookup,
      minPrice: Math.min(...prices),
      maxPrice: Math.max(...prices),
    }
  }, [data])

  if (!memo) return null
  const { waccValues, tgValues, grid, minPrice, maxPrice } = memo

  const range = maxPrice - minPrice || 1
  // Find the "current" cell (middle row, middle col)
  const midWacc = waccValues[Math.floor(waccValues.length / 2)]
  const midTg = tgValues[Math.floor(tgValues.length / 2)]

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <div className="heatmap-container">
          <table className="heatmap" role="table">
            <thead>
              <tr>
                <th className="corner" style={{ fontSize: '0.65rem' }}>
                  <span style={{ color: 'var(--accent)' }}>WACC</span>
                  {' \\ '}
                  <span style={{ color: 'var(--chart-1)' }}>TGR</span>
                </th>
                {tgValues.map((tg) => (
                  <th key={tg}>{(tg * 100).toFixed(1)}%</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {waccValues.map((wacc) => (
                <tr key={wacc}>
                  <th>{(wacc * 100).toFixed(1)}%</th>
                  {tgValues.map((tg) => {
                    const price = grid.get(`${wacc}_${tg}`)
                    const normalised = price != null ? (price - minPrice) / range : 0.5
                    const isCurrent = wacc === midWacc && tg === midTg
                    return (
                      <td
                        key={`${wacc}_${tg}`}
                        className={`${heatmapClass(normalised)}${isCurrent ? ' current' : ''}`}
                      >
                        {price != null ? `$${price.toFixed(2)}` : '\u2014'}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div
          data-testid="heatmap-legend"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 12,
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-muted)',
            letterSpacing: '0.03em',
          }}
        >
          <span>{t('chart.sensitivity.legend.lower')}</span>
          <span
            aria-hidden
            style={{
              display: 'flex',
              flex: '0 0 auto',
              height: 10,
              borderRadius: 2,
              overflow: 'hidden',
              border: '1px solid var(--border-subtle)',
            }}
          >
            {/* Ramp ordered LOW→HIGH (red→green) left-to-right to match the
                "lower" → "higher" label flow; LEGEND_RAMP is HIGH→LOW so we
                walk it in reverse. */}
            {[...LEGEND_RAMP].reverse().map((c, i) => (
              <span key={i} style={{ width: 14, height: '100%', background: c }} />
            ))}
          </span>
          <span>{t('chart.sensitivity.legend.higher')}</span>
        </div>
      </div>
    </div>
  )
}
