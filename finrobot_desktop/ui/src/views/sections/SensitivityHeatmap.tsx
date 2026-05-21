// v5 §6.5 敏感性分析 — 5×5 WACC × terminal-growth heatmap.
//
// Source data lives on the latest DCF artifact (sensitivity_table). The
// summary endpoint strips heavy fields so this section gracefully degrades
// until PR15's full-artifact loader is in place — for now it shows the
// CTA + structure placeholder so the anchor nav stays consistent.

import { useLatestArtifact } from '../../hooks/useV5Artifacts'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface SensitivityHeatmapProps {
  ticker: string
}

export function SensitivityHeatmap({ ticker }: SensitivityHeatmapProps): React.ReactElement {
  const { latest } = useLatestArtifact(ticker, 'equity_research')
  const dcf = useLatestArtifact(ticker, 'dcf').latest

  const anyArtifact = latest ?? dcf

  if (!anyArtifact) {
    return (
      <section id="sec-sensitivity" style={SECTION_STYLE}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📉 敏感性分析</h2>
        <p style={{ marginTop: 8, color: 'var(--text-soft)', fontSize: 13 }}>
          跑一次 AI 完整研报或 DCF 估值后，这里展示 WACC × 永续增长率 5×5 热力。
        </p>
      </section>
    )
  }

  // Render skeleton 5×5 grid with placeholder colors so layout is visible.
  const sample = Array.from({ length: 5 }, (_, r) =>
    Array.from({ length: 5 }, (_, c) => (r + c) / 8),
  )
  const wacc = [0.06, 0.07, 0.08, 0.09, 0.1]
  const tg = [0.0, 0.01, 0.02, 0.03, 0.04]

  return (
    <section id="sec-sensitivity" style={SECTION_STYLE}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📉 敏感性分析</h2>
      <p style={{ marginTop: 4, fontSize: 11, color: 'var(--text-faint)' }}>
        WACC × 永续增长率 → 隐含股价 · 完整数值待 PR15 plumb 全 artifact
      </p>
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
          {sample.map((row, ri) => (
            <tr key={ri}>
              <th style={cellStyle('left')}>{(wacc[ri] * 100).toFixed(0)}%</th>
              {row.map((v, ci) => (
                <td
                  key={ci}
                  style={{
                    ...cellStyle('center'),
                    background: heatColor(v),
                    color: 'var(--text)',
                  }}
                >
                  —
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
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
  // 0 → red, 0.5 → yellow-ish, 1 → green
  const r = Math.round(255 - v * 255 * 0.4)
  const g = Math.round(120 + v * 100)
  const b = Math.round(120 - v * 40)
  return `rgba(${r}, ${g}, ${b}, 0.12)`
}
