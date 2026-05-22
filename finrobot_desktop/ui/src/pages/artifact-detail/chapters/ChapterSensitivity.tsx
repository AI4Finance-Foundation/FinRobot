// Chapter 06 — Sensitivity Analysis. Three-subchapter layout mirroring
// FinRobot's structure: Key Assumptions / Confidence Intervals /
// Sensitivity Notes. DCFResult.sensitivity_table populates the matrix
// when present (compute.dcf produces a 2D map of WACC × growth rate).

import { Chapter, SubChapter } from './ChapterBase'
import type { DcfShape } from './types'

export function ChapterSensitivity({ dcf }: { dcf: DcfShape | null }): React.ReactElement {
  const table = dcf?.sensitivity_table ?? null
  const inputs = dcf?.inputs

  return (
    <Chapter id="sensitivity" num="06" title="Sensitivity Analysis" sub="Assumptions · CIs · Notes">
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
              {' '}revenue CAGR{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(meanArray(inputs.revenue_growth_rates) * 100).toFixed(1)}%
              </strong>
              ,
            </>
          )}
          {inputs?.ebitda_margin !== undefined && (
            <>
              {' '}terminal EBITDA margin{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(inputs.ebitda_margin * 100).toFixed(1)}%
              </strong>
              ,
            </>
          )}
          {dcf?.wacc !== undefined && (
            <>
              {' '}WACC{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(dcf.wacc * 100).toFixed(2)}%
              </strong>
              ,
            </>
          )}
          {inputs?.terminal_growth_rate !== undefined && (
            <>
              {' '}terminal growth{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(inputs.terminal_growth_rate * 100).toFixed(2)}%
              </strong>
              .
            </>
          )}
        </p>
      </SubChapter>

      <SubChapter heading="Sensitivity Matrix">
        {table && Object.keys(table).length > 0 ? (
          <pre
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11.5,
              color: 'var(--text-secondary)',
              background: 'rgba(15, 15, 34, 0.6)',
              padding: 14,
              borderRadius: 'var(--radius-sm)',
              overflow: 'auto',
              border: '1px solid var(--border-soft)',
              lineHeight: 1.65,
              margin: 0,
            }}
          >
            {JSON.stringify(table, null, 2)}
          </pre>
        ) : (
          <p style={mutedNote}>
            该 artifact 未保存 sensitivity_table — compute/dcf 在 v2 之后开始持久化此矩阵，重跑后此处会渲染 5×5 WACC × CAGR 热力网格。
          </p>
        )}
      </SubChapter>

      <SubChapter heading="Sensitivity Notes">
        <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
          Target valuation is most sensitive to <strong style={{ color: 'var(--text-primary)' }}>terminal EBIT margin</strong>{' '}
          and <strong style={{ color: 'var(--text-primary)' }}>terminal growth rate</strong>. WACC sensitivity is asymmetric due to
          non-linear discount-rate compounding. Revenue CAGR has comparatively muted impact unless paired with margin compression.
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
