// v5 §6.10 同业对标 — 5+ rows (target highlighted + peer rows).
// Pulls outputs.structured.peer_analysis from the equity_research artifact
// (or outputs.structured directly from a comps artifact) via useArtifactDetail.

import { useArtifactDetail, useLatestArtifact } from '../../hooks/useV5Artifacts'
import { useThesisNarrative } from '../../hooks/useThesisNarrative'

// Mirror of finagent.engine.models.financial.CompanyFinancials.
interface CompanyFinancials {
  ticker: string
  name?: string | null
  market_cap?: number | null
  pe_ratio?: number | null
  ev_ebitda?: number | null
  revenue?: number | null
  gross_margin?: number | null
  operating_margin?: number | null
}

interface PeerComps {
  target?: CompanyFinancials
  peers?: CompanyFinancials[]
  median_pe?: number | null
  median_ev_ebitda?: number | null
}

interface EquityResearchStructured {
  peer_analysis?: PeerComps
}


interface PeersSectionProps {
  ticker: string
}

export function PeersSection({ ticker }: PeersSectionProps): React.ReactElement {
  const comps = useLatestArtifact(ticker, 'comps').latest
  const equity = useLatestArtifact(ticker, 'equity_research').latest
  const source = comps ?? equity
  const { data: detail, isLoading } = useArtifactDetail(source?.id)
  const thesis = useThesisNarrative(ticker)

  if (!source) {
    return (
      <section id="sec-peers" className="cosmic-card" style={{ margin: "12px 0" }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🏢 同业对标</h2>
        <p style={{ marginTop: 8, fontSize: 13, color: 'var(--text-soft)' }}>
          跑「单独同业对标」或「AI 完整研报」后，这里展示可比公司财务比较。
        </p>
      </section>
    )
  }

  // comps artifact stores PeerComps directly at outputs.structured;
  // equity_research wraps it under outputs.structured.peer_analysis.
  const structured = detail?.outputs?.structured as
    | (PeerComps & EquityResearchStructured)
    | undefined
  const peerComps: PeerComps | undefined =
    structured?.peer_analysis ?? (structured?.target ? structured : undefined)

  const target = peerComps?.target
  const peers = peerComps?.peers ?? []
  const rows: CompanyFinancials[] = target ? [target, ...peers] : peers

  return (
    <section id="sec-peers" className="cosmic-card" style={{ margin: "12px 0" }}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🏢 同业对标</h2>
      <p style={{ marginTop: 2, fontSize: 11, color: 'var(--text-faint)' }}>
        来源 {source.type} artifact · {rows.length} 家公司
        {typeof peerComps?.median_pe === 'number' &&
          ` · 同业中位 PE ${peerComps.median_pe.toFixed(1)}`}
        {typeof peerComps?.median_ev_ebitda === 'number' &&
          ` · EV/EBITDA ${peerComps.median_ev_ebitda.toFixed(1)}`}
      </p>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {!isLoading && rows.length === 0 && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>
          本次分析未生成同业表 — Headline: {source.headline}
        </p>
      )}

      {rows.length > 0 && (
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
              <th style={cellStyle('right')}>EV/EBITDA</th>
              <th style={cellStyle('right')}>毛利率</th>
              <th style={cellStyle('right')}>营业利润率</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const isTarget = i === 0 && !!target
              return (
                <tr
                  key={`${r.ticker}-${i}`}
                  data-testid={`peer-row-${r.ticker}`}
                  data-target={isTarget ? 'true' : undefined}
                  style={{ background: isTarget ? 'rgba(16,185,129,0.06)' : 'transparent' }}
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
                  <td style={cellStyle('right')}>{r.ev_ebitda?.toFixed(1) ?? '—'}</td>
                  <td style={cellStyle('right')}>{formatPct(r.gross_margin)}</td>
                  <td style={cellStyle('right')}>{formatPct(r.operating_margin)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {thesis?.competitor_analysis && (
        <NarrativeCallout
          label="竞争格局"
          icon="⚔️"
          body={thesis.competitor_analysis}
        />
      )}
    </section>
  )
}

function NarrativeCallout({
  label,
  icon,
  body,
}: {
  label: string
  icon: string
  body: string
}): React.ReactElement {
  return (
    <div
      style={{
        marginTop: 16,
        padding: '14px 16px',
        borderRadius: 'var(--radius-md)',
        background: 'rgba(34, 211, 238, 0.06)',
        border: '1px solid rgba(34, 211, 238, 0.22)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--accent-cyan)',
          marginBottom: 6,
        }}
      >
        {icon} {label}
      </div>
      <p
        style={{
          margin: 0,
          fontFamily: 'var(--font-body)',
          fontSize: 13,
          color: 'var(--text-secondary)',
          lineHeight: 1.65,
        }}
      >
        {body}
      </p>
    </div>
  )
}

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
