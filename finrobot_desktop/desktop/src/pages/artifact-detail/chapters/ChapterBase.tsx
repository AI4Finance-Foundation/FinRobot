// Shared structural primitives used by every chapter in the
// 13-chapter investment-bank-grade long-scroll report.

import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../../i18n'
import { chapterLabel, type ChapterId } from './labels'
import { SourcedNumber, type NumberSource } from '../../../components/SourcedNumber'

/** A single KV cell. `value` is pre-formatted (currency/percent/raw) by the
 * chapter. When `source` is present, the value gets a hover provenance popover
 * (provider + fetched_at) so every provider-sourced number is traceable —
 * the headline "数字可溯源" contract (CLAUDE.md 数据正确性). */
export interface KvCell {
  label: ReactNode
  value: string
  delta?: ReactNode
  tone?: 'up' | 'down'
  source?: NumberSource
}

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
            textShadow: '0 0 12px color-mix(in srgb, var(--secondary) 50%, transparent)',
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
        background:
          'linear-gradient(160deg, color-mix(in srgb, var(--accent-cyan) 6%, transparent), transparent)',
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

export function KvGrid({
  cells,
  columns = 4,
}: {
  cells: KvCell[]
  columns?: number
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        gap: 1,
        background: 'var(--border-grid)',
        border: '1px solid var(--border-grid)',
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
            {c.source ? <SourcedNumber value={c.value} source={c.source} /> : c.value}
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
  background: 'var(--table-surface)',
  borderRadius: 'var(--radius-sm)',
  overflow: 'hidden',
}

/** Horizontal-scroll wrapper for `tableStyle` tables. The report's middle
 * column is narrow (between a 184px TOC and a 268px right rail); a wide table
 * — DCF forecast with many year columns, peer comps — otherwise overflows its
 * column and slides under the right-rail cards (they paint later in DOM order).
 * Scrolling within the column keeps every cell reachable instead of hidden.
 * `minWidth: 0` lets the wrapper shrink inside the grid so it actually clips
 * and scrolls rather than forcing the column wider. */
export function TableScroll({ children }: { children: ReactNode }): React.ReactElement {
  return <div style={{ overflowX: 'auto', maxWidth: '100%', minWidth: 0 }}>{children}</div>
}
