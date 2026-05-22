// Chapter 04 — Valuation Analysis. DCF anchor + LLM valuation_overview
// narrative. The football-field visualization that triangulates across
// DCF / Comps / DDM / LBO lives on the workspace; here we expose the
// canonical implied-price + WACC + terminal assumptions for audit.

import { Chapter, KvGrid, Narrative } from './ChapterBase'
import type { DcfShape, ThesisShape } from './types'

interface ChapterValuationProps {
  dcf: DcfShape | null
  thesis: ThesisShape | null
}

export function ChapterValuation({ dcf, thesis }: ChapterValuationProps): React.ReactElement {
  const overview = thesis?.valuation_overview ?? null
  const wacc = dcf?.wacc ?? null
  const terminalGrowth = dcf?.inputs?.terminal_growth_rate ?? null
  const taxRate = dcf?.inputs?.tax_rate ?? null
  const beta = dcf?.inputs?.beta ?? null
  const implied = dcf?.implied_price ?? null
  const ev = dcf?.enterprise_value ?? null
  const eq = dcf?.equity_value ?? null

  type Cell = { label: string; value: string; delta?: string; tone?: 'up' | 'down' }
  const cells: Cell[] = [
    wacc !== null && ({ label: 'WACC', value: `${(wacc * 100).toFixed(2)}%`, delta: beta !== null ? `β ${beta.toFixed(2)}` : undefined } as Cell),
    terminalGrowth !== null && ({ label: 'Terminal Growth', value: `${(terminalGrowth * 100).toFixed(2)}%` } as Cell),
    taxRate !== null && ({ label: 'Tax Rate', value: `${(taxRate * 100).toFixed(0)}%` } as Cell),
    implied !== null && ({
      label: 'DCF Implied Price',
      value: `$${implied.toFixed(2)}`,
      tone: (thesis?.price_target && implied >= thesis.price_target ? 'up' : undefined) as 'up' | undefined,
    } as Cell),
    ev !== null && ({ label: 'Enterprise Value', value: fmtTrillions(ev) } as Cell),
    eq !== null && ({ label: 'Equity Value', value: fmtTrillions(eq) } as Cell),
  ].filter((c): c is Cell => Boolean(c))

  return (
    <Chapter
      id="valuation"
      num="04"
      title="Valuation Analysis"
      sub="DCF · WACC · Terminal Value · Implied Price"
    >
      {overview && (
        <Narrative>
          <p>{overview}</p>
        </Narrative>
      )}

      {cells.length > 0 ? (
        <KvGrid cells={cells} columns={3} />
      ) : (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            padding: '14px 18px',
            background: 'rgba(15, 15, 34, 0.5)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          该 artifact 缺 DCF 输出 — 跑 research pipeline 可生成完整估值模型。
        </p>
      )}

      {thesis?.price_target && (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--text-secondary)',
            marginTop: 12,
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>12-Month Target:</span>{' '}
          <span style={{ color: 'var(--accent-cyan)', fontSize: 14 }}>
            ${thesis.price_target.toFixed(2)}
          </span>
          {thesis.price_target_basis && (
            <span style={{ color: 'var(--text-muted)', marginLeft: 10 }}>
              · {thesis.price_target_basis}
            </span>
          )}
        </p>
      )}
    </Chapter>
  )
}

function fmtTrillions(v: number): string {
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  return `$${v.toFixed(0)}`
}
