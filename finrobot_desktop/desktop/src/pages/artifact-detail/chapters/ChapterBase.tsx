// Shared structural primitives used by every chapter in the
// 13-chapter investment-bank-grade long-scroll report.

import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../../i18n'
import { chapterLabel, type ChapterId } from './labels'

interface ChapterProps {
  id: ChapterId
  /** Optional override — usually omit; the title is read from chapterLabel(id, locale). */
  num?: string
  title?: string
  sub?: string
  children: ReactNode
}

export function Chapter({
  id,
  num: numOverride,
  title: titleOverride,
  sub: subOverride,
  children,
}: ChapterProps): React.ReactElement {
  const { locale } = useI18n()
  const label = chapterLabel(id, locale)
  const num = numOverride ?? label.num
  const title = titleOverride ?? label.title
  const sub = subOverride ?? label.sub
  return (
    <section
      id={id}
      data-testid={`chapter-${id}`}
      style={{
        margin: '48px 0 0',
        scrollMarginTop: 84,
      }}
    >
      {/* Editorial section header: accent (cosmic --secondary) mono number + tight-set display title
          on the left, dim mono tag-row on the right, single hairline divider.
          Flat — no glow (the document's restraint is the design). */}
      <header
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 16,
          marginBottom: 22,
          paddingBottom: 13,
          borderBottom: '1px solid var(--border-soft)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 13, minWidth: 0 }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              color: 'var(--secondary)',
              letterSpacing: '0.02em',
            }}
          >
            {num}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 23,
              fontWeight: 600,
              letterSpacing: '-0.3px',
              color: 'var(--text-primary)',
            }}
          >
            {title}
          </span>
        </div>
        {sub && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--text-dim)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              whiteSpace: 'nowrap',
              flexShrink: 0,
              paddingBottom: 2,
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
  // Restrained editorial prose: a dim "+ AI NARRATIVE" provenance kicker (the
  // deterministic-vs-LLM boundary, CLAUDE.md 核心契约①) over plain body copy,
  // marked by a thin accent (cosmic --secondary) rule. No heavy fill — the document stays calm.
  return (
    <div
      style={{
        paddingLeft: 15,
        margin: '14px 0 24px',
        borderLeft: '2px solid color-mix(in srgb, var(--secondary) 55%, transparent)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--text-muted)',
          letterSpacing: '0.14em',
          marginBottom: 9,
        }}
      >
        + AI NARRATIVE
      </div>
      <div style={{ fontSize: 14.5, lineHeight: 1.75, color: 'var(--text-secondary)' }}>
        {children}
      </div>
    </div>
  )
}

export function SubChapter({
  heading,
  children,
}: {
  heading: ReactNode
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

export const tableStyle: CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  margin: '12px 0',
  background: 'var(--table-surface)',
  borderRadius: 'var(--radius-sm)',
  overflow: 'hidden',
}

/** Horizontal-scroll wrapper for `tableStyle` tables. The report's content
 * column is bounded by the two-column grid (a 248px left rail takes the
 * remaining width); a wide table — DCF forecast with many year columns, peer
 * comps — otherwise overflows its column.
 * Scrolling within the column keeps every cell reachable instead of hidden.
 * `minWidth: 0` lets the wrapper shrink inside the grid so it actually clips
 * and scrolls rather than forcing the column wider. */
export function TableScroll({ children }: { children: ReactNode }): React.ReactElement {
  return <div style={{ overflowX: 'auto', maxWidth: '100%', minWidth: 0 }}>{children}</div>
}
