// Left-side sticky table of contents for the 12-chapter report.
// Highlights the active chapter via IntersectionObserver scroll-spy.

import { useEffect, useState } from 'react'

export interface TOCEntry {
  id: string       // matches <section id="..."> on the chapter
  num: string      // "00" .. "11"
  title: string    // investment-bank tone label
}

interface ReportTOCProps {
  entries: TOCEntry[]
}

export function ReportTOC({ entries }: ReportTOCProps): React.ReactElement {
  const [activeId, setActiveId] = useState<string>(entries[0]?.id ?? '')

  useEffect(() => {
    if (entries.length === 0) return
    const observer = new IntersectionObserver(
      (rows) => {
        rows.forEach((row) => {
          if (row.isIntersecting) {
            setActiveId(row.target.id)
          }
        })
      },
      { rootMargin: '-30% 0px -60% 0px' },
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
        padding: '18px 0',
        borderRight: '1px solid var(--border-faint)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '2.5px',
          color: 'var(--text-muted)',
          marginBottom: 14,
          paddingRight: 14,
        }}
      >
        REPORT NAV
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
              padding: '7px 14px 7px 16px',
              color: isActive ? 'var(--secondary)' : 'var(--text-muted)',
              textDecoration: 'none',
              fontFamily: 'var(--font-body)',
              fontSize: 12,
              borderLeft: `2px solid ${isActive ? 'var(--secondary)' : 'transparent'}`,
              background: isActive ? 'rgba(139, 92, 246, 0.08)' : 'transparent',
              boxShadow: isActive ? '-1px 0 12px rgba(139, 92, 246, 0.3)' : 'none',
              transition: 'all 0.18s',
              marginRight: 14,
              borderRadius: '0 6px 6px 0',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: isActive ? 'var(--secondary)' : 'var(--text-dim)',
                marginRight: 8,
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
