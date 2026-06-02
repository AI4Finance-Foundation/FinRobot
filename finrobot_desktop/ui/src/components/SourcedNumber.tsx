/**
 * SourcedNumber — displays a financial number with a hover popover
 * showing data provenance (provider, fetched_at, formula, warnings).
 *
 * Accessibility: focusable via keyboard (tabIndex=0), Enter/Space triggers popover.
 * Popover auto-flips at viewport edges.
 * Source fields are optional — if all absent, the popover is suppressed.
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useI18n } from '../i18n'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface NumberSource {
  provider?: string
  fetched_at?: string
  formula_id?: string
  formula_warning?: string
  artifact_id?: string
}

export interface SourcedNumberProps {
  value: number | string | null | undefined
  source?: NumberSource
  format?: (v: number) => string
  /** Optional class for the outer span */
  className?: string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const EM_DASH = '—'
const HOVER_DELAY_MS = 200

// ── Helpers ───────────────────────────────────────────────────────────────────

function hasContent(source: NumberSource | undefined): boolean {
  if (!source) return false
  return !!(
    source.provider ||
    source.fetched_at ||
    source.formula_id ||
    source.formula_warning ||
    source.artifact_id
  )
}

function formatValue(
  value: number | string | null | undefined,
  format?: (v: number) => string,
): string {
  if (value === null || value === undefined) return EM_DASH
  if (typeof value === 'number') {
    if (isNaN(value)) return EM_DASH
    return format ? format(value) : value.toLocaleString()
  }
  return value || EM_DASH
}

function formatFetchedAt(iso: string | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SourcedNumber({ value, source, format, className }: SourcedNumberProps) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLSpanElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Ticker is needed to build the deep link to the artifact detail page.
  // SourcedNumber renders inside ticker-scoped routes (workspace / artifact
  // detail); when rendered elsewhere (tests, future cross-ticker views) the
  // ticker is undefined and the "open report" link is hidden.
  const { ticker } = useParams<{ ticker?: string }>()

  const showPopover = hasContent(source)
  const displayed = formatValue(value, format)
  // A data-quality caveat must be visible at a glance in dense tables — not
  // hidden behind a hover popover (analysts scan dozens of rows). Render an
  // inline amber marker whenever a formula warning is attached.
  const hasWarning = !!source?.formula_warning

  // ── Position ────────────────────────────────────────────────────────────────

  const [flipTop, setFlipTop] = useState(false)
  const [flipRight, setFlipRight] = useState(false)

  const recalcPosition = useCallback(() => {
    if (!triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    setFlipTop(window.innerHeight - rect.bottom < 180)
    setFlipRight(window.innerWidth - rect.right < 220)
  }, [])

  // ── Hover handlers ──────────────────────────────────────────────────────────

  const handleMouseEnter = useCallback(() => {
    if (!showPopover) return
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
    hoverTimerRef.current = setTimeout(() => {
      recalcPosition()
      setOpen(true)
    }, HOVER_DELAY_MS)
  }, [showPopover, recalcPosition])

  const handleMouseLeave = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current)
      hoverTimerRef.current = null
    }
    closeTimerRef.current = setTimeout(() => {
      setOpen(false)
    }, HOVER_DELAY_MS)
  }, [])

  const handlePopoverMouseEnter = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }, [])

  const handlePopoverMouseLeave = useCallback(() => {
    closeTimerRef.current = setTimeout(() => {
      setOpen(false)
    }, HOVER_DELAY_MS)
  }, [])

  // ── Keyboard ─────────────────────────────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!showPopover) return
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        recalcPosition()
        setOpen((o) => !o)
      }
      if (e.key === 'Escape') {
        setOpen(false)
      }
    },
    [showPopover, recalcPosition],
  )

  // ── Cleanup ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current)
    }
  }, [])

  // ── Render ───────────────────────────────────────────────────────────────────

  const popoverStyle: React.CSSProperties = {
    position: 'absolute',
    zIndex: 9999,
    minWidth: 200,
    maxWidth: 280,
    padding: '10px 12px',
    borderRadius: 6,
    background: 'var(--elevated)',
    border: '1px solid var(--border)',
    boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
    fontSize: '0.75rem',
    lineHeight: 1.5,
    color: 'var(--text-secondary)',
    // Vertical positioning
    ...(flipTop ? { bottom: '100%', marginBottom: 6 } : { top: '100%', marginTop: 6 }),
    // Horizontal positioning
    ...(flipRight ? { right: 0 } : { left: 0 }),
  }

  return (
    <span
      ref={triggerRef}
      role={showPopover ? 'button' : undefined}
      tabIndex={showPopover ? 0 : undefined}
      aria-label={
        showPopover
          ? `${displayed} — ${hasWarning ? 'has data warning; ' : ''}click for data source`
          : undefined
      }
      aria-expanded={showPopover ? open : undefined}
      aria-haspopup={showPopover ? 'dialog' : undefined}
      className={className}
      style={{
        position: 'relative',
        display: 'inline-block',
        outline: 'none',
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onKeyDown={handleKeyDown}
      onFocus={showPopover ? handleMouseEnter : undefined}
      onBlur={showPopover ? handleMouseLeave : undefined}
    >
      <span
        style={{
          borderBottom: showPopover ? '1px dotted var(--text-muted)' : undefined,
          cursor: showPopover ? 'help' : undefined,
        }}
      >
        {displayed}
      </span>

      {hasWarning && <WarningGlyph label={source?.formula_warning ?? ''} />}

      {showPopover && open && source && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label={t('sourced.title')}
          style={popoverStyle}
          onMouseEnter={handlePopoverMouseEnter}
          onMouseLeave={handlePopoverMouseLeave}
        >
          <ProvRow label={t('sourced.provider')} value={source.provider ?? t('sourced.unknown')} />
          {source.fetched_at && (
            <ProvRow label={t('sourced.fetchedAt')} value={formatFetchedAt(source.fetched_at)} />
          )}
          {source.formula_id && (
            <ProvRow label={t('sourced.formula')} value={source.formula_id} mono />
          )}
          {source.formula_warning && (
            <ProvRow label={t('sourced.warning')} value={source.formula_warning} warn />
          )}
          {source.artifact_id && ticker && (
            <div style={{ marginTop: 8 }}>
              <a
                href={`/stocks/${ticker}/runs/${source.artifact_id}`}
                style={{
                  color: 'var(--accent)',
                  fontSize: '0.72rem',
                  textDecoration: 'underline',
                  cursor: 'pointer',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                {t('sourced.openReport')}
              </a>
            </div>
          )}
        </div>
      )}
    </span>
  )
}

function ProvRow({
  label,
  value,
  mono,
  warn,
}: {
  label: string
  value: string
  mono?: boolean
  warn?: boolean
}) {
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 3 }}>
      <span style={{ color: 'var(--text-muted)', minWidth: 56, flexShrink: 0 }}>{label}:</span>
      <span
        style={{
          // Caveat = caution (amber --warning), not a price loss (red). Keeps
          // 涨绿跌红 intact: red stays reserved for price-down semantics.
          color: warn ? 'var(--warning)' : 'var(--text-primary)',
          fontFamily: mono ? 'var(--font-mono)' : undefined,
          fontSize: mono ? '0.7rem' : undefined,
          wordBreak: 'break-all',
        }}
      >
        {value}
      </span>
    </div>
  )
}

/**
 * WarningGlyph — small inline amber triangle marking a numbers with a
 * data-quality caveat. Inline SVG (per cosmic spec: simple icons hand-drawn),
 * all colors via var(--*), accessible name via aria-label (no <title> child so
 * the warning text doesn't leak into text-content queries).
 */
function WarningGlyph({ label }: { label: string }) {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 16 16"
      role="img"
      aria-label={label}
      style={{ marginLeft: 3, verticalAlign: '-1px', flexShrink: 0 }}
    >
      <path
        d="M8 2 L14.5 13.5 H1.5 Z"
        fill="var(--warning-soft)"
        stroke="var(--warning)"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <line
        x1="8"
        y1="6.2"
        x2="8"
        y2="9.6"
        stroke="var(--warning)"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="8" cy="11.4" r="0.85" fill="var(--warning)" />
    </svg>
  )
}
