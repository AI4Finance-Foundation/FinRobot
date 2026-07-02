// Financial Analysis — base-year profit cascade (replaces the flat 3-cell KvGrid
// for chapter 04 only; the shared KvGrid stays untouched).
//
// Revenue → EBITDA → Net Income is a single nested proportion: each step is a
// fraction of the top line. The flat grid rendered them as three disconnected,
// equal-width cards, erasing that structure. This renders them as horizontal
// nested bars whose widths ARE the margins, so the top-line → bottom-line
// narrowing is read at a glance. The multi-year trend charts below are unchanged
// — this is the single base-year snapshot, not a time series.
//
// Margins are computed from the real figures (raw EBITDA/Net ÷ raw Revenue); a
// negative step (a loss) turns red (涨绿跌红) and clamps its bar to zero width.
// Every money figure is a <SourcedNumber> (provenance preserved). Rows are
// rendered only when present; with no revenue reference the bars are suppressed
// and the figures still show. Colours are var(--*) tokens only.

import type { ReactNode } from 'react'
import { SourcedNumber, type NumberSource } from '../../../components/SourcedNumber'

export type WaterfallTone = 'rev' | 'ebitda' | 'net'

export interface WaterfallRow {
  tone: WaterfallTone
  /** Row name — an isolated text node (e.g. "EBITDA" / "净利润"). */
  label: ReactNode
  /** Pre-formatted money string (reporting currency), wrapped in SourcedNumber. */
  value: string
  /** Raw amount (reporting currency) — drives bar width + margin. */
  raw: number
  source?: NumberSource
  /**
   * Optional caliber tag for the top line, its own node — e.g. "TTM · 2026-03".
   * NOT a fiscal-year badge: revenue here is a trailing-twelve-month figure
   * (see ChapterFinancialAnalysis), so the tag must say TTM, never "FYxxxx"
   * (a full fiscal year that may not even be over yet).
   */
  periodTag?: string
}

const SWATCH: Record<WaterfallTone, string> = {
  rev: 'var(--primary)',
  ebitda: 'var(--accent-cyan)',
  net: 'var(--success)',
}

function toneColor(tone: WaterfallTone, raw: number): string {
  return raw < 0 ? 'var(--danger)' : SWATCH[tone]
}

function pctText(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`
}

function Row({ row, denom }: { row: WaterfallRow; denom: number | null }): React.ReactElement {
  const color = toneColor(row.tone, row.raw)
  const ratio = denom && denom > 0 ? row.raw / denom : null
  const width =
    ratio === null ? (row.tone === 'rev' ? 100 : 0) : Math.max(0, Math.min(1, ratio)) * 100
  const isRev = row.tone === 'rev'
  const marginLabel = isRev ? '100% · TOP LINE' : ratio === null ? null : `${pctText(ratio)} MARGIN`

  return (
    <div style={{ position: 'relative' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--text-secondary)',
          }}
        >
          <span style={{ width: 9, height: 9, borderRadius: 2, background: color, flex: 'none' }} />
          <span>{row.label}</span>
          {row.periodTag && (
            <span style={{ fontSize: 10.5, color: 'var(--text-dim)', letterSpacing: '0.1em' }}>
              {row.periodTag}
            </span>
          )}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            fontSize: 18,
            color: 'var(--text-primary)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <SourcedNumber value={row.value} source={row.source} />
        </span>
      </div>

      <div
        style={{
          position: 'relative',
          height: 32,
          borderRadius: 6,
          background: 'color-mix(in srgb, var(--bg-deep) 60%, transparent)',
          border: '1px solid var(--border-grid)',
          overflow: 'hidden',
        }}
      >
        {width > 0 && (
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: 0,
              width: `${width}%`,
              borderRadius: '5px 0 0 5px',
              background: `linear-gradient(90deg, color-mix(in srgb, ${color} 48%, transparent), color-mix(in srgb, ${color} 20%, transparent))`,
              boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 45%, transparent), inset 0 0 28px -8px ${color}`,
            }}
          />
        )}
        {marginLabel && (
          <span
            style={{
              position: 'absolute',
              top: '50%',
              transform: 'translateY(-50%)',
              ...(isRev || width >= 30
                ? { right: 12, color: 'var(--text-primary)' }
                : { left: `calc(${Math.min(width, 80)}% + 10px)`, color: 'var(--text-muted)' }),
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.06em',
              textShadow: '0 1px 3px color-mix(in srgb, var(--bg-void) 80%, transparent)',
              whiteSpace: 'nowrap',
            }}
          >
            {marginLabel}
          </span>
        )}
      </div>
    </div>
  )
}

export function ProfitWaterfall({ rows }: { rows: WaterfallRow[] }): React.ReactElement | null {
  if (rows.length === 0) return null
  const revRow = rows.find((r) => r.tone === 'rev')
  const denom = revRow && revRow.raw > 0 ? revRow.raw : null

  return (
    <div
      style={{
        position: 'relative',
        background: 'var(--bg-card)',
        border: '1px solid var(--border-grid)',
        borderRadius: 'var(--radius-sm)',
        padding: '24px 28px 22px',
        margin: '16px 0',
        overflow: 'hidden',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        {rows.map((r) => (
          <Row key={r.tone} row={r} denom={denom} />
        ))}
      </div>
      <div
        style={{
          marginTop: 18,
          paddingTop: 12,
          borderTop: '1px solid var(--border-grid)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--text-dim)',
          textAlign: 'right',
        }}
      >
        Profit cascade · top-line → bottom-line
      </div>
    </div>
  )
}
