// v5 §6.10 同业对标 — 5 行表格 (target 高亮 + 4 peers).
// Reads the latest comps artifact via PR1 v5 hooks; falls back to a CTA
// when no peer_analysis has run yet. Doesn't touch the user's in-flight
// PeersTab — wires through the artifact store instead.

import { useLatestArtifact } from '../../hooks/useV5Artifacts'

interface CompanyFinancials {
  ticker: string
  name?: string | null
  market_cap?: number | null
  pe_ratio?: number | null
  ebitda?: number | null
  revenue?: number | null
  gross_margin?: number | null
  operating_margin?: number | null
}

interface PeerCompsStructured {
  target?: CompanyFinancials
  peers?: CompanyFinancials[]
  median_pe?: number | null
  median_ev_ebitda?: number | null
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface PeersSectionProps {
  ticker: string
}

export function PeersSection({ ticker }: PeersSectionProps): React.ReactElement {
  // Try comps artifact first; fall back to equity_research's peer_analysis output.
  const comps = useLatestArtifact(ticker, 'comps').latest
  const equity = useLatestArtifact(ticker, 'equity_research').latest

  // Summary endpoint strips the heavy `outputs.structured.peer_analysis`
  // payload — we'd need a full-Artifact loader to pull peer rows. Plumb
  // that in PR15. For now show the headline + a CTA so the section anchors
  // remain consistent and the section isn't empty when a comps artifact
  // exists.
  const latest = comps ?? equity
  const placeholder: PeerCompsStructured = {}

  if (!latest) {
    return (
      <section id="sec-peers" style={SECTION_STYLE}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🏢 同业对标</h2>
        <p style={{ marginTop: 8, fontSize: 13, color: 'var(--text-soft)' }}>
          跑「单独同业对标」或「AI 完整研报」后，这里展示 5 家可比公司财务比较。
        </p>
      </section>
    )
  }

  // Render the placeholder structure so the section has a stable layout
  // and tests can pin selectors; numbers come in PR15's full-Artifact wire.
  const rows: CompanyFinancials[] = [
    { ticker, name: latest.headline?.slice(0, 24) ?? ticker, market_cap: null, pe_ratio: null },
  ]

  return (
    <section id="sec-peers" style={SECTION_STYLE}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🏢 同业对标</h2>
      <p style={{ marginTop: 2, fontSize: 11, color: 'var(--text-faint)' }}>
        来源 {latest.type} artifact · 完整 peer 表格待 PR15 plumb 全 artifact
      </p>
      <table
        data-testid="peers-table"
        style={{
          marginTop: 12,
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 12,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <thead>
          <tr style={{ color: 'var(--text-faint)' }}>
            <th style={cellStyle('left')}>公司</th>
            <th style={cellStyle('right')}>市值</th>
            <th style={cellStyle('right')}>PE</th>
            <th style={cellStyle('right')}>营收增长</th>
            <th style={cellStyle('right')}>毛利率</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={r.ticker}
              data-testid={`peer-row-${r.ticker}`}
              style={{ background: i === 0 ? 'rgba(16,185,129,0.06)' : 'transparent' }}
            >
              <td style={cellStyle('left')}>
                <strong>{r.ticker}</strong>
                {r.name && (
                  <span style={{ marginLeft: 6, color: 'var(--text-faint)', fontSize: 11 }}>
                    {r.name}
                  </span>
                )}
              </td>
              <td style={cellStyle('right')}>{formatMoney(r.market_cap)}</td>
              <td style={cellStyle('right')}>{r.pe_ratio?.toFixed(1) ?? '—'}</td>
              <td style={cellStyle('right')}>—</td>
              <td style={cellStyle('right')}>{formatPct(r.gross_margin)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ marginTop: 8, fontSize: 11, color: 'var(--text-faint)' }}>
        Headline: {latest.headline}
      </p>
    </section>
  )
}

// Suppress unused-import warning for the placeholder structured type — kept
// as documentation of the shape PR15 will plumb.
export type { PeerCompsStructured }

function cellStyle(align: 'left' | 'right'): React.CSSProperties {
  return {
    padding: '6px 8px',
    borderBottom: '1px solid var(--border-soft)',
    textAlign: align,
  }
}

function formatMoney(v?: number | null): string {
  if (v === undefined || v === null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toLocaleString()}`
}

function formatPct(v?: number | null): string {
  if (v === undefined || v === null) return '—'
  return `${(v * 100).toFixed(1)}%`
}
