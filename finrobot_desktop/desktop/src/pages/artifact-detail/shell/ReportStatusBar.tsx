// Bottom status bar for the 13-chapter report — Zed-inspired.
//
// Sticky to the viewport bottom, ~28px tall. Surfaces the current chapter
// (via scroll-spy on the same section ids the TOC observes), a scroll
// progress percentage, and a back-to-top control. Returning to the doc is
// owned by the breadcrumb + toolbar arrow, not a bottom "back" button —
// desktop apps (Linear / Notion / Obsidian / Apple Mail) don't put a return
// control at the foot of a reading view.
//
// Scroll events are bound to the REAL scroll container: #main-scroll
// (<main id="main-scroll" class="main-content"> in AppShell). The body /
// window never scrolls — body is overflow:hidden and the main pane is the
// only element with overflow-y:auto. window.scrollY is always 0.

import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../../i18n'
import type { TOCEntry } from './ReportTOC'

interface ReportStatusBarProps {
  entries: TOCEntry[]
}

export function ReportStatusBar({ entries }: ReportStatusBarProps): React.ReactElement {
  const { t } = useI18n()
  const [activeIdx, setActiveIdx] = useState<number>(0)
  const [progressPct, setProgressPct] = useState<number>(0)
  // Cache the scroll container reference so both effects share the same node.
  const scrollElRef = useRef<HTMLElement | null>(null)

  function getScrollEl(): HTMLElement | null {
    if (scrollElRef.current) return scrollElRef.current
    const el = document.getElementById('main-scroll')
    scrollElRef.current = el
    return el
  }

  // Scroll-spy on the same section ids the TOC tracks. root: scrollEl so
  // IntersectionObserver correctly observes against the pane, not viewport.
  useEffect(() => {
    if (entries.length === 0) return
    const scrollEl = getScrollEl()
    const observer = new IntersectionObserver(
      (rows) => {
        rows.forEach((row) => {
          if (row.isIntersecting) {
            const idx = entries.findIndex((e) => e.id === row.target.id)
            if (idx !== -1) setActiveIdx(idx)
          }
        })
      },
      {
        root: scrollEl ?? null, // null = viewport (safe fallback if not found)
        rootMargin: '-30% 0px -60% 0px',
      },
    )
    entries.forEach((e) => {
      const el = document.getElementById(e.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [entries])

  // Document scroll progress. rAF-throttled so we don't recompute on
  // every scroll event — the bar only needs to feel "alive", not pixel-perfect.
  // Listens on the REAL scroll container (not window).
  useEffect(() => {
    const scrollEl = getScrollEl()
    if (!scrollEl) return

    let raf: number | null = null

    function compute(): void {
      raf = null
      const el = scrollElRef.current
      if (!el) return
      const scrollTop = el.scrollTop
      const max = el.scrollHeight - el.clientHeight
      const pct = max > 0 ? Math.min(100, Math.max(0, (scrollTop / max) * 100)) : 0
      setProgressPct(pct)
    }

    function onScroll(): void {
      if (raf !== null) return
      raf = requestAnimationFrame(compute)
    }

    compute()
    scrollEl.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      scrollEl.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf !== null) cancelAnimationFrame(raf)
    }
  }, [])

  function scrollToTop(): void {
    const scrollEl = getScrollEl()
    if (scrollEl) {
      scrollEl.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  const total = entries.length
  const current = entries[activeIdx]
  const chapterLabel = current ? `${current.num} · ${current.title}` : ''

  return (
    <div
      data-testid="report-status-bar"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: 28,
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        background: 'var(--bg-sticky-92)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        borderTop: '1px solid var(--border-faint)',
        fontFamily: 'var(--font-mono)',
        fontSize: 10.5,
        color: 'var(--text-muted)',
        letterSpacing: '0.04em',
        zIndex: 25,
      }}
    >
      <div
        aria-hidden
        style={{
          position: 'absolute',
          left: 0,
          bottom: 0,
          height: 2,
          width: `${progressPct}%`,
          background: 'linear-gradient(90deg, var(--primary), var(--secondary))',
          transition: 'width 0.12s linear',
          boxShadow: '0 0 8px color-mix(in srgb, var(--primary) 50%, transparent)',
        }}
      />

      <span data-testid="report-status-chapter" style={{ color: 'var(--text-secondary)' }}>
        {t('report.statusBar.chapter')} {String(activeIdx + 1).padStart(2, '0')}/
        {String(total).padStart(2, '0')}
        {chapterLabel && (
          <span style={{ color: 'var(--text-dim)', marginLeft: 8 }}>{chapterLabel}</span>
        )}
      </span>

      <span style={{ flex: 1 }} />

      <span
        data-testid="report-status-progress"
        style={{ color: 'var(--text-dim)', marginRight: 14 }}
      >
        {progressPct.toFixed(0)}%
      </span>

      <button
        type="button"
        data-testid="report-status-back-to-top"
        onClick={scrollToTop}
        title={t('report.statusBar.backToTop')}
        style={backTopBtnStyle}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = 'var(--accent-cyan)'
          e.currentTarget.style.background =
            'color-mix(in srgb, var(--accent-cyan) 8%, transparent)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = 'var(--text-secondary)'
          e.currentTarget.style.background = 'transparent'
        }}
      >
        ↑ {t('report.statusBar.backToTopShort')}
      </button>
    </div>
  )
}

const backTopBtnStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  padding: '3px 10px',
  border: 'none',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  letterSpacing: '0.04em',
  borderRadius: 4,
  transition: 'all 0.18s',
}
