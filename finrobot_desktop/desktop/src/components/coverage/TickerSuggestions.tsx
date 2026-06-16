// TickerSuggestions — the homepage autocomplete dropdown (design "Variant C:
// analyst hero-symbol"). The ticker is the hero (mono), the company name a quiet
// muted sub-line; the matched substring is emphasised by WEIGHT (not colour) so
// it stays calm/analyst-grade. The active row gets a left accent bar + elevated
// fill + a ↵ hint. Only real fields are shown (symbol + name) — no price /
// exchange / logo, which the SEC universe doesn't carry (§1.6 honest UI).
//
// Presentational only: open/active state and keyboard nav live in CoverageHero.

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { tSync } from '../../i18n'
import type { SymbolSuggestion } from '../../api/search'

interface TickerSuggestionsProps {
  results: SymbolSuggestion[]
  activeIndex: number
  query: string
  labelId: string
  onSelect: (symbol: string) => void
  onHover: (index: number) => void
}

// Bold the leading run of `text` that matches `q` as a prefix (used for the
// ticker symbol). Case-insensitive; no match → plain text.
function boldPrefix(text: string, q: string): ReactNode {
  const query = q.trim()
  if (query && text.toLowerCase().startsWith(query.toLowerCase())) {
    return (
      <>
        <strong style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
          {text.slice(0, query.length)}
        </strong>
        {text.slice(query.length)}
      </>
    )
  }
  return text
}

// Bold the prefix of any word in `name` that starts with `q` (used for the
// company name, e.g. "ap" → **Ap**ple).
function boldNameWords(name: string, q: string): ReactNode {
  const query = q.trim().toLowerCase()
  if (!query) return name
  // Split keeping separators so the name renders verbatim.
  const parts = name.split(/(\s+)/)
  return parts.map((part, i) => {
    if (part.toLowerCase().startsWith(query)) {
      return (
        <span key={i}>
          <strong style={{ fontWeight: 700 }}>{part.slice(0, query.length)}</strong>
          {part.slice(query.length)}
        </span>
      )
    }
    return <span key={i}>{part}</span>
  })
}

function RowGlyph({ active }: { active: boolean }): ReactNode {
  const color = active ? 'var(--accent-cyan)' : 'var(--text-muted)'
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden style={{ flexShrink: 0 }}>
      <rect
        x="1.5"
        y="1.5"
        width="11"
        height="11"
        rx="2.5"
        fill="none"
        stroke={color}
        strokeWidth="1.2"
      />
      <circle cx="7" cy="7" r="1.6" fill={color} />
    </svg>
  )
}

export function TickerSuggestions({
  results,
  activeIndex,
  query,
  labelId,
  onSelect,
  onHover,
}: TickerSuggestionsProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null)
  const rowRefs = useRef<(HTMLDivElement | null)[]>([])
  const [maxHeight, setMaxHeight] = useState<number | undefined>(undefined)

  // Cap the dropdown to the gap between its top and the viewport bottom so a long
  // list scrolls INSIDE the panel instead of running off-screen and unreachable.
  useLayoutEffect(() => {
    function measure(): void {
      const el = containerRef.current
      if (!el) return
      setMaxHeight(Math.max(180, window.innerHeight - el.getBoundingClientRect().top - 16))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [results.length])

  // Keep the keyboard-highlighted row in view as the user arrows down/up.
  useLayoutEffect(() => {
    if (activeIndex >= 0) rowRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  return (
    <div
      ref={containerRef}
      id={labelId}
      role="listbox"
      aria-label={tSync('landing.hero.suggestionsAria')}
      data-testid="ticker-suggestions"
      // Keep focus on the input when a row is clicked (mousedown fires before
      // blur) so the dropdown doesn't close out from under the click.
      onMouseDown={(e) => e.preventDefault()}
      style={{
        position: 'absolute',
        top: 'calc(100% + 8px)',
        left: 0,
        right: 0,
        zIndex: 20,
        background: 'var(--bg-card)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        boxShadow: '0 12px 40px rgba(0,0,0,0.45)',
        maxHeight,
        overflowY: 'auto',
        overscrollBehavior: 'contain',
        paddingBottom: 4,
      }}
    >
      {/* top gradient hairline */}
      <div
        aria-hidden
        style={{
          height: 1,
          background: 'linear-gradient(90deg, var(--primary), transparent)',
        }}
      />
      <div
        style={{
          padding: '8px 14px 6px',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color: 'var(--text-dim)',
        }}
      >
        {tSync('landing.hero.suggestionsLabel')}
      </div>

      {results.map((r, i) => {
        const active = i === activeIndex
        return (
          <div
            key={r.symbol}
            ref={(el) => {
              rowRefs.current[i] = el
            }}
            id={`ticker-opt-${i}`}
            role="option"
            aria-selected={active}
            data-testid={`suggestion-${r.symbol}`}
            data-active={active || undefined}
            onClick={() => onSelect(r.symbol)}
            onMouseEnter={() => onHover(i)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              minHeight: 44,
              padding: '7px 16px 7px 14px',
              borderLeft: `2px solid ${active ? 'var(--primary)' : 'transparent'}`,
              background: active ? 'var(--bg-elevated)' : 'transparent',
              cursor: 'pointer',
            }}
          >
            <RowGlyph active={active} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 15,
                  fontWeight: 600,
                  letterSpacing: '0.03em',
                  color: 'var(--text-primary)',
                }}
              >
                {boldPrefix(r.symbol, query)}
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-body)',
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {boldNameWords(r.name, query)}
              </div>
            </div>
            {active && (
              <span
                aria-hidden
                style={{
                  flexShrink: 0,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--accent-cyan)',
                }}
              >
                ↵
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
