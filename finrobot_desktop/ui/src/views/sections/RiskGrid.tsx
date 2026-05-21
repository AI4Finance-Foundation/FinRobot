// v5 §6.3 风险因素 — 2×2 risk-card grid sourced from the latest
// equity_research artifact's thesis step output. Falls back to a CTA when
// no analysis exists yet.

import { useLatestArtifact } from '../../hooks/useV5Artifacts'

interface ThesisRisk {
  severity?: 'high' | 'med' | 'low'
  title?: string
  description?: string
  source?: string
}

interface ThesisStructured {
  risks?: ThesisRisk[]
}

interface EquityResearchOutputs {
  thesis?: ThesisStructured
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface RiskGridProps {
  ticker: string
}

export function RiskGrid({ ticker }: RiskGridProps): React.ReactElement {
  const { latest } = useLatestArtifact(ticker, 'equity_research')

  // The summary endpoint strips heavy fields — risks live on the full Artifact.
  // For now we surface only what the summary headline already carries plus a
  // CTA. PR15 will plumb full artifact loading through useArtifactDetail.
  const placeholderRisks: ThesisRisk[] = []

  if (!latest) {
    return (
      <section id="sec-risk" style={SECTION_STYLE}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>⚠️ 风险因素</div>
        <p style={{ marginTop: 8, color: 'var(--text-soft)', fontSize: 13 }}>
          跑一次 AI 完整研报后，这里展示 AI 提取的风险因素（来源 thesis step）。
        </p>
      </section>
    )
  }

  return (
    <section id="sec-risk" style={SECTION_STYLE}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>⚠️ 风险因素</div>
      <p style={{ marginTop: 4, fontSize: 11, color: 'var(--text-faint)' }}>
        来源 thesis step · 完整 risks 数组待 PR15 plumb 全 artifact 加载
      </p>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 10,
          marginTop: 12,
        }}
      >
        {placeholderRisks.length > 0
          ? placeholderRisks.map((risk, idx) => <RiskCard key={idx} risk={risk} />)
          : (
              <div style={{ gridColumn: '1 / -1', fontSize: 12, color: 'var(--text-faint)' }}>
                Headline: {latest.headline}
              </div>
            )}
      </div>
    </section>
  )
}

function RiskCard({ risk }: { risk: ThesisRisk }): React.ReactElement {
  const severity = risk.severity ?? 'med'
  const color = severity === 'high' ? '#EF4444' : severity === 'med' ? '#F59E0B' : '#10B981'
  return (
    <article
      style={{
        border: `1px solid ${color}33`,
        borderLeft: `4px solid ${color}`,
        borderRadius: 6,
        padding: 12,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600 }}>{risk.title ?? '(未命名风险)'}</div>
      <p style={{ marginTop: 4, fontSize: 11.5, color: 'var(--text-soft)' }}>
        {risk.description ?? ''}
      </p>
      {risk.source && (
        <p style={{ marginTop: 4, fontSize: 10.5, color: 'var(--text-faint)' }}>
          来源：{risk.source}
        </p>
      )}
    </article>
  )
}

// Suppress unused-import warning for the structured types — they're the
// contract surface that PR15 will use when it switches to the full Artifact
// loader. Keeping them here documents the shape we expect.
export type { EquityResearchOutputs }
