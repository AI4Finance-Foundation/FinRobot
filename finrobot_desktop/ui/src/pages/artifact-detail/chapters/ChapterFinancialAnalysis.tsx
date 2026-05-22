// Chapter 03 — Financial Analysis. Pairs the artifact-frozen base-year
// financials (from inputs.raw_data, captured at run time) with the DCF
// step's 3-year forecast (projected_revenue / projected_ebitda /
// projected_fcf). FinRobot has a similar mix — historicals + forecasts.

import { Chapter, KvGrid, SubChapter, tableStyle } from './ChapterBase'
import type { DcfShape } from './types'

interface ChapterFinancialAnalysisProps {
  dcf: DcfShape | null
  rawData: Record<string, unknown> | null
}

export function ChapterFinancialAnalysis({
  dcf,
  rawData,
}: ChapterFinancialAnalysisProps): React.ReactElement {
  const baseRev = (rawData?.revenue as number | undefined) ?? dcf?.inputs?.revenue_base ?? null
  const baseEbitda = (rawData?.ebitda as number | undefined) ?? null
  const baseNet = (rawData?.net_income as number | undefined) ?? null
  const fcfTtm = (rawData?.fcf_ttm as number | undefined) ?? null

  const cells = [
    baseRev !== null && {
      label: 'Revenue (Base)',
      value: fmtBillions(baseRev),
      delta: rawData?.fiscal_year ? `FY${rawData.fiscal_year}` : undefined,
    },
    baseEbitda !== null && { label: 'EBITDA', value: fmtBillions(baseEbitda) },
    baseNet !== null && { label: 'Net Income', value: fmtBillions(baseNet) },
    fcfTtm !== null && { label: 'FCF TTM', value: fmtBillions(fcfTtm) },
  ].filter((c): c is { label: string; value: string; delta?: string } => c !== false)

  return (
    <Chapter
      id="financial"
      num="03"
      title="Financial Analysis"
      sub="Base Year · 3Y Forecast · Key Ratios"
    >
      {cells.length > 0 && <KvGrid cells={cells} columns={4} />}

      {dcf?.projected_revenue && dcf.projected_revenue.length > 0 && (
        <SubChapter heading="DCF Forecast (Code-Computed)">
          <table style={tableStyle}>
            <thead style={{ background: 'var(--bg-elevated)' }}>
              <tr>
                <th style={thStyle}>$B</th>
                {dcf.projected_revenue.map((_, i) => (
                  <th key={i} style={thStyle}>
                    Year +{i + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                  Revenue
                </td>
                {dcf.projected_revenue.map((v, i) => (
                  <td key={i} style={{ ...tdStyle, textAlign: 'right' }}>
                    {fmtBillions(v)}
                  </td>
                ))}
              </tr>
              {dcf.projected_ebitda && dcf.projected_ebitda.length > 0 && (
                <tr>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                    EBITDA
                  </td>
                  {dcf.projected_ebitda.map((v, i) => (
                    <td key={i} style={{ ...tdStyle, textAlign: 'right' }}>
                      {fmtBillions(v)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_fcf && dcf.projected_fcf.length > 0 && (
                <tr>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                    Free Cash Flow
                  </td>
                  {dcf.projected_fcf.map((v, i) => (
                    <td key={i} style={{ ...tdStyle, textAlign: 'right', color: 'var(--accent-cyan)' }}>
                      {fmtBillions(v)}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
          <p
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-dim)',
              marginTop: 6,
              letterSpacing: '0.04em',
            }}
          >
            Source: 10-K filings + compute/forward_estimates.py (deterministic)
          </p>
        </SubChapter>
      )}

      {cells.length === 0 && !dcf?.projected_revenue && (
        <p style={emptyMsg}>该 artifact 未保存财务输入 — 重跑 research 后此处补齐。</p>
      )}
    </Chapter>
  )
}

function fmtBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toFixed(0)}`
}

const thStyle: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 500,
  fontSize: 10.5,
  color: 'var(--secondary)',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  borderBottom: '1px solid var(--border-soft)',
}
const tdStyle: React.CSSProperties = {
  padding: '9px 14px',
  borderBottom: '1px solid var(--border-faint)',
  color: 'var(--text-secondary)',
  fontVariantNumeric: 'tabular-nums',
}
const emptyMsg: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'rgba(15, 15, 34, 0.5)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
