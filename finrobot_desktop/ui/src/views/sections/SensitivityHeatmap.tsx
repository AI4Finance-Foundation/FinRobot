// v5 §6.5 敏感性分析 — N×N WACC × terminal-growth implied-price heatmap.
//
// Data source: outputs.structured.sensitivity_table for a `dcf` artifact, or
// outputs.structured.financial_modeling.sensitivity_table for an
// `equity_research` artifact. Shape is
//   { wacc_values: number[], tg_values: number[], implied_prices: (number|null)[][] }
// per finagent.engine.compute.dcf.calculate_sensitivity.

import { useArtifactDetail, useLatestArtifact } from '../../hooks/useV5Artifacts'

interface SensitivityTable {
  wacc_values?: number[]
  tg_values?: number[]
  implied_prices?: (number | null)[][]
}

interface DCFStructured extends SensitivityTable {
  sensitivity_table?: SensitivityTable
  implied_price?: number
}

interface EquityResearchStructured {
  financial_modeling?: DCFStructured
}


interface SensitivityHeatmapProps {
  ticker: string
}

export function SensitivityHeatmap({ ticker }: SensitivityHeatmapProps): React.ReactElement {
  const equity = useLatestArtifact(ticker, 'equity_research').latest
  const dcf = useLatestArtifact(ticker, 'dcf').latest
  const source = equity ?? dcf
  const { data: detail, isLoading } = useArtifactDetail(source?.id)

  if (!source) {
    return (
      <section id="sec-sensitivity" className="cosmic-card" style={{ margin: "12px 0" }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📉 敏感性分析</h2>
        <p style={{ marginTop: 8, color: 'var(--text-soft)', fontSize: 13 }}>
          跑一次 AI 完整研报或 DCF 估值后，这里展示 WACC × 永续增长率 5×5 隐含股价矩阵。
        </p>
      </section>
    )
  }

  const structured = detail?.outputs?.structured as
    | (DCFStructured & EquityResearchStructured)
    | undefined
  const sens =
    structured?.financial_modeling?.sensitivity_table ??
    structured?.sensitivity_table ??
    null

  const wacc = sens?.wacc_values ?? []
  const tg = sens?.tg_values ?? []
  const grid = sens?.implied_prices ?? []
  const flat = grid.flat().filter((v): v is number => typeof v === 'number')
  const min = flat.length ? Math.min(...flat) : 0
  const max = flat.length ? Math.max(...flat) : 0
  const span = max - min || 1

  return (
    <section id="sec-sensitivity" className="cosmic-card" style={{ margin: "12px 0" }}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📉 敏感性分析</h2>
      <p style={{ marginTop: 4, fontSize: 11, color: 'var(--text-faint)' }}>
        WACC × 永续增长率 → 隐含股价 · 数据来自 {source.type} artifact
      </p>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {!isLoading && wacc.length === 0 && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>
          本次分析未生成敏感性表（可能是计算 fallback 触发了 simple-DCF 路径）。
        </p>
      )}

      {wacc.length > 0 && (
        <table
          data-testid="sensitivity-table"
          style={{
            marginTop: 12,
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 11,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <thead>
            <tr>
              <th style={cellStyle()}>WACC \ g</th>
              {tg.map((g) => (
                <th key={g} style={cellStyle()}>
                  {(g * 100).toFixed(1)}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.map((row, ri) => (
              <tr key={ri}>
                <th style={cellStyle('left')}>{((wacc[ri] ?? 0) * 100).toFixed(1)}%</th>
                {row.map((price, ci) => (
                  <td
                    key={ci}
                    style={{
                      ...cellStyle('center'),
                      background: price !== null ? heatColor((price - min) / span) : 'transparent',
                      color: 'var(--text)',
                    }}
                  >
                    {price !== null ? `$${price.toFixed(0)}` : '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function cellStyle(align: 'left' | 'center' | 'right' = 'center'): React.CSSProperties {
  return {
    border: '1px solid var(--border-soft)',
    padding: '4px 8px',
    textAlign: align,
    color: 'var(--text-soft)',
  }
}

function heatColor(v: number): string {
  // 0 → red-ish, 0.5 → neutral, 1 → green-ish (cheap-to-expensive ramp).
  const clamped = Math.max(0, Math.min(1, v))
  const r = Math.round(255 - clamped * 255 * 0.4)
  const g = Math.round(120 + clamped * 100)
  const b = Math.round(120 - clamped * 40)
  return `rgba(${r}, ${g}, ${b}, 0.18)`
}
