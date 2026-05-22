// v5 §6.3 风险因素 — 2×N grid sourced from the equity_research artifact's
// thesis step (outputs.structured.thesis.risks). Falls back to a CTA when
// no analysis exists yet.

import { useArtifactDetail, useLatestArtifact } from '../../hooks/useV5Artifacts'

interface ThesisStructured {
  risks?: string[]
}

interface EquityResearchStructured {
  thesis?: ThesisStructured
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card)',
}

interface RiskGridProps {
  ticker: string
}

export function RiskGrid({ ticker }: RiskGridProps): React.ReactElement {
  const { latest } = useLatestArtifact(ticker, 'equity_research')
  const { data: detail, isLoading } = useArtifactDetail(latest?.id)

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

  const structured = (detail?.outputs?.structured ?? {}) as EquityResearchStructured
  const risks = structured.thesis?.risks ?? []

  return (
    <section id="sec-risk" style={SECTION_STYLE}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>
        ⚠️ 风险因素
        {risks.length > 0 && (
          <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-faint)', fontWeight: 400 }}>
            · {risks.length} 项 · 来源 thesis step
          </span>
        )}
      </div>
      {isLoading && (
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {!isLoading && risks.length === 0 && (
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--text-faint)' }}>
          本次研报未识别明确风险点 — Headline: {latest.headline}
        </p>
      )}
      {risks.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 10,
            marginTop: 12,
          }}
        >
          {risks.map((r, i) => (
            <RiskCard key={i} text={r} />
          ))}
        </div>
      )}
    </section>
  )
}

function RiskCard({ text }: { text: string }): React.ReactElement {
  return (
    <article
      style={{
        border: '1px solid var(--border-soft)',
        borderLeft: '4px solid #F59E0B',
        borderRadius: 6,
        padding: 12,
        fontSize: 12,
        lineHeight: 1.55,
        color: 'var(--text)',
      }}
    >
      {text}
    </article>
  )
}
