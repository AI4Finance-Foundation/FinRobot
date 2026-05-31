// Left-side sticky table of contents for the 13-chapter report.
// Highlights the active chapter via IntersectionObserver scroll-spy.
//
// IntersectionObserver root is set to #main-scroll (the real scroll
// container in AppShell). Using the default viewport root would never fire
// because body is overflow:hidden and window never scrolls.

import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n'

export interface TOCEntry {
  id: string // matches <section id="..."> on the chapter
  num: string // "01" .. "12"
  title: string // investment-bank tone label
}

interface ReportTOCProps {
  entries: TOCEntry[]
}

export function ReportTOC({ entries }: ReportTOCProps): React.ReactElement {
  const { t } = useI18n()
  const label = t('report.toc.heading')
  const [activeId, setActiveId] = useState<string>(entries[0]?.id ?? '')

  useEffect(() => {
    if (entries.length === 0) return

    // Resolve the real scroll container. document.getElementById is safe to
    // call in useEffect (DOM is committed). Falls back to null (= viewport)
    // so the observer degrades gracefully in tests / unusual environments.
    const scrollEl = document.getElementById('main-scroll')

    const observer = new IntersectionObserver(
      (rows) => {
        rows.forEach((row) => {
          if (row.isIntersecting) {
            setActiveId(row.target.id)
          }
        })
      },
      {
        root: scrollEl ?? null,
        rootMargin: '-30% 0px -60% 0px',
      },
    )
    entries.forEach((e) => {
      const el = document.getElementById(e.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [entries])

  return (
    <aside
      data-testid="report-toc"
      style={{
        position: 'sticky',
        top: 82,
        alignSelf: 'start',
        maxHeight: 'calc(100vh - 100px)',
        overflowY: 'auto',
        padding: '14px 0',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 10,
          letterSpacing: '2px',
          color: 'var(--text-muted)',
          marginBottom: 10,
          paddingLeft: 10,
        }}
      >
        {label}
      </div>
      {entries.map((entry) => {
        const isActive = entry.id === activeId
        return (
          <a
            key={entry.id}
            href={`#${entry.id}`}
            data-testid={`toc-${entry.id}`}
            data-active={isActive ? 'true' : 'false'}
            style={{
              display: 'block',
              padding: '5px 8px 5px 10px',
              color: isActive ? 'var(--secondary)' : 'var(--text-muted)',
              textDecoration: 'none',
              fontFamily: 'var(--font-body)',
              fontSize: 11,
              lineHeight: 1.35,
              borderLeft: `2px solid ${isActive ? 'var(--secondary)' : 'transparent'}`,
              background: isActive ? 'rgba(139, 92, 246, 0.08)' : 'transparent',
              boxShadow: isActive ? '-1px 0 12px rgba(139, 92, 246, 0.3)' : 'none',
              transition: 'all 0.18s',
              marginRight: 8,
              borderRadius: '0 5px 5px 0',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9.5,
                color: isActive ? 'var(--secondary)' : 'var(--text-dim)',
                marginRight: 6,
              }}
            >
              {entry.num}
            </span>
            {entry.title}
          </a>
        )
      })}
    </aside>
  )
}
