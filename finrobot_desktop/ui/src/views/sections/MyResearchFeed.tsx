// v5 §6.14 我的研究 — artifact feed grouped by type badge with signal dot.
// Sources: PR1's GET /api/artifacts/by-ticker/{ticker}/timeline.

import { useV5ArtifactTimeline } from '../../hooks/useV5Artifacts'
import type { ArtifactSummaryV5 } from '../../types/v5'
import { StatBanner } from './StatBanner'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

const TYPE_META: Record<string, { label: string; color: string }> = {
  equity_research: { label: 'AI 研报', color: '#10B981' },
  dcf: { label: 'DCF', color: '#3B82F6' },
  ic_memo: { label: '投委备忘', color: '#8B5CF6' },
  earnings: { label: '财报分析', color: '#F97316' },
  earnings_analysis: { label: '财报分析', color: '#F97316' },
  lbo: { label: 'LBO', color: '#EC4899' },
  comps: { label: '同业对标', color: '#14B8A6' },
  ddm: { label: 'DDM', color: '#8B5CF6' },
  playground_snapshot: { label: '手调假设', color: '#6B7280' },
  ad_hoc: { label: 'Ad hoc', color: '#9CA3AF' },
  peer_research: { label: '同业研究', color: '#14B8A6' },
}

interface MyResearchFeedProps {
  ticker: string
}

export function MyResearchFeed({ ticker }: MyResearchFeedProps): React.ReactElement | null {
  const { data, isLoading } = useV5ArtifactTimeline(ticker)
  const artifacts = data ?? []
  // Spec §6.14: hide entire section (and its anchor) when 0 artifacts.
  if (!isLoading && artifacts.length === 0) return null

  return (
    <section id="sec-research" style={SECTION_STYLE}>
      <header
        style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}
      >
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📚 我的研究</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          {artifacts.length} 份分析
        </span>
      </header>

      <StatBanner ticker={ticker} artifacts={artifacts} />

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}

      <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
        {artifacts.map((a) => (
          <ArtifactCard key={a.id} artifact={a} />
        ))}
      </div>
    </section>
  )
}

function ArtifactCard({ artifact }: { artifact: ArtifactSummaryV5 }): React.ReactElement {
  const meta = TYPE_META[artifact.type] ?? TYPE_META.ad_hoc
  const dotColor =
    artifact.signal === 'hit'
      ? '#10B981'
      : artifact.signal === 'failed'
        ? '#EF4444'
        : artifact.signal === 'watching'
          ? '#F59E0B'
          : 'transparent'
  return (
    <article
      data-testid={`artifact-card-${artifact.id}`}
      data-signal={artifact.signal ?? 'none'}
      style={{
        border: '1px solid var(--border-soft)',
        borderLeft: artifact.signal
          ? `4px solid ${dotColor}`
          : '1px solid var(--border-soft)',
        borderRadius: 6,
        padding: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: dotColor,
          opacity: artifact.signal ? 1 : 0,
        }}
      />
      <span
        style={{
          fontSize: 10.5,
          fontWeight: 600,
          padding: '2px 6px',
          borderRadius: 4,
          background: `${meta.color}1A`,
          color: meta.color,
          minWidth: 56,
          textAlign: 'center',
        }}
      >
        {meta.label}
      </span>
      <span style={{ flex: 1, fontSize: 12.5 }}>
        <strong>{artifact.headline}</strong>
        <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-faint)' }}>
          {formatRelative(artifact.created_at)} · {artifact.source}
        </span>
        {artifact.target_price !== null && artifact.entry_price !== null && (
          <div style={{ fontSize: 11, color: 'var(--text-soft)', marginTop: 2 }}>
            target ${artifact.target_price.toFixed(2)} · entry ${artifact.entry_price.toFixed(2)}
          </div>
        )}
      </span>
    </article>
  )
}

function formatRelative(iso: string): string {
  const d = new Date(iso)
  const diffH = (Date.now() - d.getTime()) / (3600 * 1000)
  if (diffH < 24) return `${Math.max(1, Math.round(diffH))}h 前`
  if (diffH < 24 * 14) return `${Math.round(diffH / 24)}d 前`
  return d.toLocaleDateString('zh-CN')
}
