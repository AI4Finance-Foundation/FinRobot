// Shared structural primitives used by every chapter in the
// FinRobot-parity 12-chapter long-scroll report.

import type { CSSProperties, ReactNode } from 'react'

interface ChapterProps {
  id: string
  num: string
  title: string
  sub?: string
  children: ReactNode
}

export function Chapter({ id, num, title, sub, children }: ChapterProps): React.ReactElement {
  return (
    <section
      id={id}
      data-testid={`chapter-${id}`}
      style={{
        margin: '40px 0 64px',
        scrollMarginTop: 84,
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 18,
          marginBottom: 22,
          paddingBottom: 12,
          borderBottom: '1px solid var(--border-soft)',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            color: 'var(--secondary)',
            letterSpacing: '2px',
            textShadow: '0 0 12px rgba(139, 92, 246, 0.5)',
          }}
        >
          {num}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 22,
            letterSpacing: '2px',
            color: 'var(--text-primary)',
          }}
        >
          {title}
        </span>
        {sub && (
          <span
            style={{
              marginLeft: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--text-muted)',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            {sub}
          </span>
        )}
      </header>
      {children}
    </section>
  )
}

export function Narrative({ children }: { children: ReactNode }): React.ReactElement {
  return (
    <div
      style={{
        background: 'linear-gradient(160deg, rgba(34, 211, 238, 0.06), transparent)',
        borderLeft: '2px solid var(--accent-cyan)',
        padding: '14px 18px',
        margin: '12px 0 22px',
        fontSize: 13.5,
        lineHeight: 1.7,
        color: 'var(--text-secondary)',
        borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          color: 'var(--accent-cyan)',
          letterSpacing: '0.16em',
          marginBottom: 6,
          opacity: 0.85,
        }}
      >
        🤖 AI NARRATIVE
      </div>
      {children}
    </div>
  )
}

export function SubChapter({
  heading,
  children,
}: {
  heading: string
  children: ReactNode
}): React.ReactElement {
  return (
    <div style={{ margin: '22px 0' }}>
      <h4
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 12.5,
          fontWeight: 600,
          color: 'var(--text-primary)',
          letterSpacing: '0.04em',
          marginBottom: 10,
          textTransform: 'uppercase',
        }}
      >
        {heading}
      </h4>
      {children}
    </div>
  )
}

export function KvGrid({
  cells,
  columns = 4,
}: {
  cells: { label: string; value: string; delta?: string; tone?: 'up' | 'down' }[]
  columns?: number
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        gap: 1,
        background: 'var(--border-data, rgba(255,255,255,0.08))',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 'var(--radius-sm)',
        overflow: 'hidden',
        margin: '16px 0',
      }}
    >
      {cells.map((c, i) => (
        <div key={i} style={{ background: 'var(--bg-card)', padding: '14px 16px' }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--text-muted)',
              letterSpacing: '0.04em',
              marginBottom: 4,
              textTransform: 'uppercase',
            }}
          >
            {c.label}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 18,
              color:
                c.tone === 'up'
                  ? 'var(--success)'
                  : c.tone === 'down'
                    ? 'var(--danger)'
                    : 'var(--text-primary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {c.value}
          </div>
          {c.delta && (
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--text-muted)',
                marginTop: 2,
              }}
            >
              {c.delta}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export const tableStyle: CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  margin: '12px 0',
  background: 'rgba(15, 15, 34, 0.4)',
  borderRadius: 'var(--radius-sm)',
  overflow: 'hidden',
}
