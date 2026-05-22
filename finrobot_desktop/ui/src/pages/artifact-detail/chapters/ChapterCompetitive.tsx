// Chapter 09 — Competitive Landscape. Surfaces PeerComps target +
// peers table (P/E, EV/EBITDA, margins) alongside the LLM-synthesised
// competitor_analysis narrative. FinRobot has parallel
// Gross Margin / SG&A / EBITDA Margin subchapters — we expose
// gross_margin / operating_margin from peers for like-for-like compare.

import { Chapter, Narrative, SubChapter, tableStyle } from './ChapterBase'
import type { PeerCompsShape, ThesisShape } from './types'

interface ChapterCompetitiveProps {
  peers: PeerCompsShape | null
  thesis: ThesisShape | null
}

export function ChapterCompetitive({
  peers,
  thesis,
}: ChapterCompetitiveProps): React.ReactElement {
  const narrative = thesis?.competitor_analysis ?? null
  const target = peers?.target
  const peerList = peers?.peers ?? []
  const all = target ? [target, ...peerList] : peerList

  return (
    <Chapter
      id="competitive"
      num="09"
      title="Competitive Landscape"
      sub="Peer Comps · Margin Compare"
    >
      {narrative && (
        <Narrative>
          <p>{narrative}</p>
        </Narrative>
      )}

      {all.length > 0 ? (
        <table style={tableStyle}>
          <thead style={{ background: 'var(--bg-elevated)' }}>
            <tr>
              <th style={thStyle}>Ticker</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Revenue</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>P/E</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>EV/EBITDA</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Gross Margin</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Op Margin</th>
            </tr>
          </thead>
          <tbody>
            {all.map((c, i) => {
              const isTarget = i === 0 && target !== undefined
              return (
                <tr
                  key={c.ticker}
                  style={
                    isTarget
                      ? { background: 'rgba(34, 211, 238, 0.06)' }
                      : undefined
                  }
                >
                  <td
                    style={{
                      ...tdStyle,
                      color: isTarget ? 'var(--accent-cyan)' : 'var(--text-primary)',
                      fontWeight: 500,
                    }}
                  >
                    {c.ticker}
                    {c.name && (
                      <span
                        style={{
                          marginLeft: 8,
                          color: 'var(--text-muted)',
                          fontSize: 11,
                          fontWeight: 300,
                        }}
                      >
                        {c.name}
                      </span>
                    )}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    ${(c.revenue / 1e9).toFixed(1)}B
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {c.pe_ratio !== null && c.pe_ratio !== undefined ? c.pe_ratio.toFixed(1) : '—'}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {c.ev_ebitda !== null && c.ev_ebitda !== undefined ? c.ev_ebitda.toFixed(1) : '—'}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {(c.gross_margin * 100).toFixed(1)}%
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {(c.operating_margin * 100).toFixed(1)}%
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <p style={mutedNote}>该 artifact 未保存 peer_analysis — 跑 research 后此处补齐</p>
      )}

      {(peers?.median_pe !== null && peers?.median_pe !== undefined) ||
      (peers?.median_ev_ebitda !== null && peers?.median_ev_ebitda !== undefined) ? (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            marginTop: 6,
          }}
        >
          Peer median:
          {peers.median_pe !== null && peers.median_pe !== undefined && (
            <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>
              P/E {peers.median_pe.toFixed(1)}
            </span>
          )}
          {peers.median_ev_ebitda !== null && peers.median_ev_ebitda !== undefined && (
            <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>
              EV/EBITDA {peers.median_ev_ebitda.toFixed(1)}
            </span>
          )}
        </p>
      ) : null}

      {peers?.positioning_narrative && (
        <SubChapter heading="Positioning vs Peers">
          <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
            {peers.positioning_narrative}
          </p>
        </SubChapter>
      )}
    </Chapter>
  )
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
const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'rgba(15, 15, 34, 0.5)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
