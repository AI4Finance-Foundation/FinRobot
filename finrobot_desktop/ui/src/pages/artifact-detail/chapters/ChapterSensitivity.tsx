import SensitivityHeatmap from '../../../components/charts/SensitivityHeatmap'
import { Chapter, SubChapter } from './ChapterBase'
import type { DcfShape } from './types'

interface SensitivityTableShape {
  wacc_values?: number[]
  tg_values?: number[]
  implied_prices?: number[][]
}

function flattenSensitivity(
  table: Record<string, unknown> | null | undefined,
): { wacc: number; tg: number; implied_price: number }[] {
  if (!table) return []
  const t = table as SensitivityTableShape
  const waccs = Array.isArray(t.wacc_values) ? t.wacc_values : []
  const tgs = Array.isArray(t.tg_values) ? t.tg_values : []
  const prices = Array.isArray(t.implied_prices) ? t.implied_prices : []
  const rows: { wacc: number; tg: number; implied_price: number }[] = []
  for (let i = 0; i < waccs.length; i++) {
    const row = prices[i]
    if (!Array.isArray(row)) continue
    for (let j = 0; j < tgs.length; j++) {
      const price = row[j]
      if (typeof price !== 'number' || !Number.isFinite(price)) continue
      rows.push({ wacc: waccs[i], tg: tgs[j], implied_price: price })
    }
  }
  return rows
}

export function ChapterSensitivity({ dcf }: { dcf: DcfShape | null }): React.ReactElement {
  const table = dcf?.sensitivity_table ?? null
  const inputs = dcf?.inputs
  const heatmapRows = flattenSensitivity(table)

  return (
    <Chapter id="sensitivity">
      <SubChapter heading="Key Assumptions">
        <p
          style={{
            fontSize: 13,
            lineHeight: 1.7,
            color: 'var(--text-secondary)',
          }}
        >
          DCF anchors on four pivots:
          {inputs?.revenue_growth_rates && inputs.revenue_growth_rates.length > 0 && (
            <>
              {' '}
              revenue CAGR{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(meanArray(inputs.revenue_growth_rates) * 100).toFixed(1)}%
              </strong>
              ,
            </>
          )}
          {inputs?.ebitda_margin !== undefined && (
            <>
              {' '}
              terminal EBITDA margin{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(inputs.ebitda_margin * 100).toFixed(1)}%
              </strong>
              ,
            </>
          )}
          {dcf?.wacc !== undefined && (
            <>
              {' '}
              WACC{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(dcf.wacc * 100).toFixed(2)}%
              </strong>
              ,
            </>
          )}
          {inputs?.terminal_growth_rate !== undefined && (
            <>
              {' '}
              terminal growth{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(inputs.terminal_growth_rate * 100).toFixed(2)}%
              </strong>
              .
            </>
          )}
        </p>
      </SubChapter>

      <SubChapter heading="Sensitivity Matrix">
        {heatmapRows.length > 0 ? (
          <SensitivityHeatmap data={heatmapRows} title="WACC × Terminal Growth → Implied Price" />
        ) : (
          <p style={mutedNote}>
            该 artifact 未保存 sensitivity_table——请重跑 research 以生成 WACC × 终值增长率热力网格。
          </p>
        )}
      </SubChapter>

      <SubChapter heading="Sensitivity Notes">
        <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
          Target valuation is most sensitive to{' '}
          <strong style={{ color: 'var(--text-primary)' }}>terminal EBIT margin</strong> and{' '}
          <strong style={{ color: 'var(--text-primary)' }}>terminal growth rate</strong>. WACC
          sensitivity is asymmetric due to non-linear discount-rate compounding. Revenue CAGR has
          comparatively muted impact unless paired with margin compression.
        </p>
      </SubChapter>
    </Chapter>
  )
}

function meanArray(arr: number[]): number {
  if (arr.length === 0) return 0
  return arr.reduce((a, b) => a + b, 0) / arr.length
}

const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'rgba(15, 15, 34, 0.5)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  lineHeight: 1.6,
}
