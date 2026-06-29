// Terminal Data Readout — a grouped, framed data module that replaces the flat
// KvGrid for the report's dense data chapters (Financial Data / Valuation /
// Technical / Ownership). The flat grid rendered every metric as an identical,
// individually-boxed cell with whitespace gutters — visually undifferentiated and
// disconnected. This frames each logical group in a single panel:
//   • an accent left RAIL + accent TITLE BAR carry the group's identity/colour
//     (income=blue, balance=cyan, valuation=violet, …), so a reader sees the
//     boundary of a statement at a glance;
//   • the cells share a CONTINUOUS HAIRLINE grid (1px seams over a tinted
//     backing — no boxed cells, no gutters), reading as one instrument, not a
//     scatter of tiles;
//   • micro-encoding is added ONLY where it's natural: a margin cell can carry an
//     inline proportion bar; a valuation panel can carry a 52-week-range
//     positioner. No gauges are forced onto fields that have no natural scale.
//
// This is a pure VISUAL container. It never computes, formats, or re-calibrates a
// number — the caller passes a pre-formatted `value` string (+ optional caliber
// `source`), exactly as it did to KvGrid. Provenance is preserved verbatim: a
// cell with a `source` renders its value through <SourcedNumber> (the 1px dotted
// underline + hover provenance popover — the 可溯源 contract), identical to
// KvGrid's behaviour. A cell without a source renders the plain string.
//
// Degradation: the caller pushes a cell ONLY when its field is present (the
// existing present-or-omit logic), so an absent field produces no cell — never a
// blank, NaN, or "undefined". A module with zero cells renders nothing.
//
// Colours come exclusively from var(--*) design tokens (no hard-coded hex); alpha
// is expressed via color-mix(), per the cosmic UI spec. The only animation is a
// ≤1s one-shot bar grow that respects prefers-reduced-motion; persistent emphasis
// is a static neon glow.

import type { CSSProperties, ReactNode } from 'react'
import { SourcedNumber, type NumberSource } from '../../../components/SourcedNumber'

// ── Read model ────────────────────────────────────────────────────────────────

/** A semantic accent for a group. Each maps to a `var(--*)` rail colour. */
export type MetricAccent = 'primary' | 'cyan' | 'violet' | 'success'

/** A single readout cell. `value` is pre-formatted (currency/percent/raw/×) by
 *  the chapter — this component never touches it. `source` (when present) routes
 *  the value through <SourcedNumber> for the dotted-underline provenance popover,
 *  byte-for-byte the same contract KvGrid honoured. */
export interface MetricCell {
  /** Field label — its own isolated text/element node (so testing-library's
   *  getByText matches it). May be a node (TermTip / FieldCaveat wrappers). */
  label: ReactNode
  /** Pre-formatted display string ("$58.12B" / "58.4%" / "48.8×"). */
  value: string
  /** Optional caliber provenance → dotted underline + hover popover. */
  source?: NumberSource
  /** Optional secondary line under the value (e.g. "TOP LINE · NET SALES"). */
  sub?: ReactNode
  /** Up/down colours the value (涨绿跌红); undefined = neutral primary text. */
  tone?: 'up' | 'down'
  /** Optional inline proportion bar fill ∈ [0,1] — only for margin-like cells.
   *  Omit for every cell that has no natural 0–100% scale. */
  ratio?: number
  /** Optional short monospace address tag shown dim beside the label
   *  (e.g. "IS·01"), terminal texture. Purely decorative. */
  addr?: string
}

/** Optional 52-week-range positioner rendered full-width inside a module. The
 *  caller supplies it ONLY when price + high + low are all present and high>low;
 *  this component renders the band + marker, never deriving or hiding a number. */
export interface RangePositioner {
  label: ReactNode
  /** Marker position ∈ [0,1] = (price − low) / (high − low), clamped by caller. */
  position: number
  /** Pre-formatted current price (+ its caliber source for the dotted popover). */
  current: string
  currentSource?: NumberSource
  /** Short cap over the current-price readout (e.g. "Current"). */
  currentCap: ReactNode
  /** Pre-formatted low / high bounds (+ optional sources). */
  low: string
  lowSource?: NumberSource
  high: string
  highSource?: NumberSource
  lowCap: ReactNode
  highCap: ReactNode
  /** Optional caption (e.g. "84% OF BAND · NEAR HIGH"). */
  caption?: ReactNode
}

export interface MetricModuleProps {
  /** Group title rendered in the accent title bar (own text node). */
  title: ReactNode
  accent: MetricAccent
  cells: MetricCell[]
  /** Cells per row inside the continuous grid. Default 3. */
  columns?: 2 | 3
  /** Optional title-bar meta chip on the right (e.g. "TTM · USD"). */
  meta?: ReactNode
  /** Optional accent chip glyph at the left of the title bar. */
  glyph?: ReactNode
  /** Optional full-width range positioner appended after the cells. */
  range?: RangePositioner
}

// ── Accent token map ────────────────────────────────────────────────────────

const ACCENT_VAR: Record<MetricAccent, string> = {
  primary: 'var(--primary)',
  cyan: 'var(--accent-cyan)',
  violet: 'var(--secondary)',
  success: 'var(--success)',
}
/** Secondary colour for the proportion-bar gradient tail (rail → rail-2). */
const ACCENT_VAR_2: Record<MetricAccent, string> = {
  primary: 'var(--accent-cyan)',
  cyan: 'var(--primary)',
  violet: 'var(--accent-cyan)',
  success: 'var(--accent-cyan)',
}

const clamp01 = (n: number): number => (n < 0 ? 0 : n > 1 ? 1 : n)

// ── Cell ────────────────────────────────────────────────────────────────────

const cellBase: CSSProperties = {
  background: 'var(--bg-card)',
  padding: '16px 18px 17px',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  minWidth: 0,
}
const cellKey: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  display: 'flex',
  alignItems: 'center',
  gap: 7,
}
const cellAddr: CSSProperties = {
  color: 'var(--text-dim)',
  fontSize: 10,
  letterSpacing: '0.06em',
  fontWeight: 500,
}
const cellSub: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  letterSpacing: '0.06em',
  color: 'var(--text-dim)',
}

function valueStyle(tone: 'up' | 'down' | undefined): CSSProperties {
  return {
    fontFamily: 'var(--font-display)',
    fontSize: 22,
    fontWeight: 600,
    lineHeight: 1.05,
    letterSpacing: '-0.3px',
    color:
      tone === 'up' ? 'var(--success)' : tone === 'down' ? 'var(--danger)' : 'var(--text-primary)',
    fontVariantNumeric: 'tabular-nums',
  }
}

/** Inline proportion bar (margin-like cells only). `var(--rail)` / `--rail-2` are
 *  set on the panel, so the fill picks up the group's accent automatically. */
function RatioBar({ fill }: { fill: number }): React.ReactElement {
  return (
    <div
      style={{
        position: 'relative',
        marginTop: 2,
        height: 6,
        borderRadius: 3,
        background: 'color-mix(in srgb, var(--bg-deep) 70%, transparent)',
        border: '1px solid var(--border-grid)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          width: `${clamp01(fill) * 100}%`,
          borderRadius: 3,
          background: 'linear-gradient(90deg, var(--rail), var(--rail-2))',
          boxShadow:
            'inset 0 0 0 1px color-mix(in srgb, var(--text-primary) 8%, transparent), 0 0 12px -2px var(--rail-glow)',
        }}
      />
    </div>
  )
}

function Cell({ cell }: { cell: MetricCell }): React.ReactElement {
  return (
    <div style={cellBase}>
      <span style={cellKey}>
        <span>{cell.label}</span>
        {cell.addr && <span style={cellAddr}>{cell.addr}</span>}
      </span>
      <div style={valueStyle(cell.tone)}>
        {cell.source ? <SourcedNumber value={cell.value} source={cell.source} /> : cell.value}
      </div>
      {cell.ratio !== undefined && <RatioBar fill={cell.ratio} />}
      {cell.sub !== undefined && cell.sub !== null && <span style={cellSub}>{cell.sub}</span>}
    </div>
  )
}

// ── 52-week range positioner ─────────────────────────────────────────────────

function RangeBlock({ range }: { range: RangePositioner }): React.ReactElement {
  const pct = clamp01(range.position) * 100
  const capStyle: CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 9.5,
    letterSpacing: '0.16em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
  }
  const boundStyle: CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 12.5,
    color: 'var(--text-secondary)',
    fontVariantNumeric: 'tabular-nums',
  }
  return (
    <div style={{ gridColumn: '1 / -1', background: 'var(--bg-card)', padding: '18px 20px 20px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 14,
          marginBottom: 16,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--text-muted)',
          }}
        >
          {range.label}
        </span>
        <span style={{ display: 'flex', flexDirection: 'column', gap: 4, textAlign: 'right' }}>
          <span style={capStyle}>{range.currentCap}</span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: 18,
              color: 'var(--secondary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            <SourcedNumber value={range.current} source={range.currentSource} />
          </span>
        </span>
      </div>

      {/* gradient band: cold (low) → warm → accent (high) */}
      <div
        style={{
          position: 'relative',
          height: 8,
          borderRadius: 4,
          background:
            'linear-gradient(90deg, color-mix(in srgb, var(--danger) 16%, transparent), color-mix(in srgb, var(--warning) 14%, transparent) 45%, color-mix(in srgb, var(--accent-cyan) 16%, transparent) 78%, color-mix(in srgb, var(--secondary) 22%, transparent))',
          border: '1px solid var(--border-grid)',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: `${pct}%`,
            transform: 'translate(-50%, -50%)',
            width: 3,
            height: 20,
            borderRadius: 2,
            background: 'var(--secondary)',
            boxShadow: '0 0 12px 1px color-mix(in srgb, var(--secondary) 90%, transparent)',
          }}
        />
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginTop: 9,
        }}
      >
        <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={boundStyle}>
            <SourcedNumber value={range.low} source={range.lowSource} />
          </span>
          <span style={capStyle}>{range.lowCap}</span>
        </span>
        {range.caption !== undefined && range.caption !== null && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              letterSpacing: '0.08em',
              color: 'var(--secondary)',
              alignSelf: 'center',
            }}
          >
            {range.caption}
          </span>
        )}
        <span style={{ display: 'flex', flexDirection: 'column', gap: 2, textAlign: 'right' }}>
          <span style={boundStyle}>
            <SourcedNumber value={range.high} source={range.highSource} />
          </span>
          <span style={capStyle}>{range.highCap}</span>
        </span>
      </div>
    </div>
  )
}

// ── Module ────────────────────────────────────────────────────────────────────

export function MetricModule({
  title,
  accent,
  cells,
  columns = 3,
  meta,
  glyph,
  range,
}: MetricModuleProps): React.ReactElement | null {
  if (cells.length === 0 && !range) return null

  const rail = ACCENT_VAR[accent]
  const rail2 = ACCENT_VAR_2[accent]
  // The accent is threaded to children as CSS custom properties so the rail,
  // title wash, chip, proportion bars and glows all derive from one source.
  const panelVars = {
    '--rail': rail,
    '--rail-2': rail2,
    '--rail-glow': `color-mix(in srgb, ${rail} 60%, transparent)`,
    '--rail-wash': `color-mix(in srgb, ${rail} 9%, transparent)`,
    '--rail-border': `color-mix(in srgb, ${rail} 32%, transparent)`,
  } as CSSProperties

  return (
    <div
      style={{
        ...panelVars,
        position: 'relative',
        background: 'var(--bg-card)',
        border: '1px solid var(--border-grid)',
        borderRadius: 'var(--radius-sm)',
        overflow: 'hidden',
        margin: '16px 0',
      }}
    >
      {/* accent rail down the left edge */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          width: 3,
          background: 'var(--rail)',
          boxShadow: '0 0 18px -2px var(--rail-glow)',
        }}
      />

      {/* accent title bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 14,
          padding: '13px 18px 13px 22px',
          background: 'linear-gradient(90deg, var(--rail-wash), transparent 78%)',
          borderBottom: '1px solid var(--border-grid)',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
          {glyph && (
            <span
              style={{
                flex: 'none',
                width: 26,
                height: 26,
                borderRadius: 6,
                border: '1px solid var(--rail-border)',
                background: 'var(--rail-wash)',
                display: 'grid',
                placeItems: 'center',
              }}
            >
              {glyph}
            </span>
          )}
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {title}
          </span>
        </span>
        {meta !== undefined && meta !== null && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--rail)',
              border: '1px solid var(--rail-border)',
              borderRadius: 4,
              padding: '2px 7px',
              background: 'var(--rail-wash)',
              whiteSpace: 'nowrap',
              flex: 'none',
            }}
          >
            {meta}
          </span>
        )}
      </div>

      {/* continuous hairline grid — 1px seams created by gap over a tinted backing */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${columns}, 1fr)`,
          gap: 1,
          background: 'var(--border-grid)',
        }}
      >
        {cells.map((c, i) => (
          <Cell key={i} cell={c} />
        ))}
        {range && <RangeBlock range={range} />}
      </div>
    </div>
  )
}
