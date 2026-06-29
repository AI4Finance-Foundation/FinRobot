// Company Overview — "instrument panel" snapshot (replaces the flat KvGrid for
// chapter 03 only; the shared KvGrid is used by 6 chapters and stays untouched).
//
// The flat grid rendered identity (sector/industry/country) and metrics
// (market cap / CAGR / gross margin / beta) as identical cells — visually
// undifferentiated. This splits them by data semantics:
//   • identity  → an icon-led PASSPORT strip (categorical tags, plain strings)
//   • metrics   → TELEMETRY tiles, each with a micro-gauge that encodes the value
//                 (radial arc for margin, 0–2 scale-marker for beta, trend glyph
//                 for CAGR, scale-ladder for market cap)
//
// Provenance is preserved verbatim: every metric value is a <SourcedNumber>, so
// the dotted underline + hover provenance popover (the 可溯源 contract) is the
// real component, not a mock. Identity strings render plain (no popover) — the
// ChapterCompanyOverview tests assert exactly this split.
//
// Degradation: identity chips and metric tiles are each rendered ONLY when their
// value is present; an absent field produces no chip/tile (never a blank, NaN,
// or "undefined"). The ticker chip and as-of cluster are likewise guarded.
//
// Colours come exclusively from var(--*) design tokens (no hard-coded hex);
// alpha is expressed via SVG *-opacity attributes or color-mix(), per the cosmic
// UI spec. No animation — persistent emphasis is a static neon glow.

import type { ReactNode } from 'react'
import { SourcedNumber, type NumberSource } from '../../../components/SourcedNumber'

// ── Read model ────────────────────────────────────────────────────────────────

export interface SnapshotIdentity {
  sector?: string
  industry?: string
  country?: string
}

export type MetricKind = 'market_cap' | 'cagr' | 'gross_margin' | 'operating_margin' | 'beta'

export interface SnapshotMetric {
  kind: MetricKind
  /** Display label, e.g. "Market Cap" / "市值" (already localised by the chapter). */
  label: string
  /** Pre-formatted display string, e.g. "$4.35T" / "47.9%" / "1.09". */
  value: string
  /** Raw numeric — drives the gauge encoding only (ratio for margin/cagr, x for beta). */
  raw: number
  source?: NumberSource
}

export interface CompanySnapshotProps {
  identity: SnapshotIdentity
  metrics: SnapshotMetric[]
  /** Quote currency for the provenance cluster ("USD"); the metric figures carry
   *  their own per-number provenance via SourcedNumber. */
  quoteCurrency?: string
  /** ISO timestamp of the snapshot — rendered as a short YYYY-MM-DD "AS OF" tag. */
  fetchedAt?: string | null
}

// ── Small helpers ───────────────────────────────────────────────────────────

const clamp01 = (n: number): number => (n < 0 ? 0 : n > 1 ? 1 : n)

/** ISO → "2026-06-18" (date only). Returns '' for anything unparseable, so the
 *  cluster simply omits the tag rather than printing a partial/garbage string. */
function isoDate(iso: string | null | undefined): string {
  if (!iso || typeof iso !== 'string') return ''
  const m = iso.match(/^\d{4}-\d{2}-\d{2}/)
  return m ? m[0] : ''
}

/** Standard, deterministic beta classification (β is a unit-free ratio). */
function betaDescriptor(beta: number): string {
  if (!Number.isFinite(beta)) return ''
  if (beta < 0.8) return 'DEFENSIVE · LOW β'
  if (beta > 1.2) return 'AGGRESSIVE · HIGH β'
  return '≈ MARKET RISK'
}

// ── Passport identity icons (generic — no country-specific flag) ─────────────

function SectorIcon(): React.ReactElement {
  // Layered chip / circuit — "sector".
  return (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none" aria-hidden="true">
      <rect
        x="3.5"
        y="3.5"
        width="10"
        height="10"
        rx="1.5"
        stroke="var(--primary)"
        strokeWidth="1.1"
      />
      <rect x="6" y="6" width="5" height="5" rx="0.6" fill="var(--primary)" fillOpacity={0.35} />
      <path
        d="M8.5 .8V3.5 M8.5 13.5v2.7 M.8 8.5H3.5 M13.5 8.5h2.7 M5.2 .8V3 M11.8 .8V3 M5.2 14v2.2 M11.8 14v2.2"
        stroke="var(--primary)"
        strokeWidth="1"
        strokeOpacity={0.7}
      />
    </svg>
  )
}

function IndustryIcon(): React.ReactElement {
  // Device / consumer-electronics — "industry".
  return (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none" aria-hidden="true">
      <rect
        x="2.5"
        y="3"
        width="12"
        height="8"
        rx="1.2"
        stroke="var(--accent-cyan)"
        strokeWidth="1.1"
      />
      <path d="M5.5 14h6" stroke="var(--accent-cyan)" strokeWidth="1.1" strokeLinecap="round" />
      <path d="M8.5 11v3" stroke="var(--accent-cyan)" strokeWidth="1.1" />
      <path
        d="M5 6h5 M5 8h3.2"
        stroke="var(--accent-cyan)"
        strokeWidth="1"
        strokeOpacity={0.7}
        strokeLinecap="round"
      />
    </svg>
  )
}

function CountryIcon(): React.ReactElement {
  // Globe + meridian — "country" (generic; works for any domicile).
  return (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none" aria-hidden="true">
      <circle cx="8.5" cy="8.5" r="6.2" stroke="var(--secondary)" strokeWidth="1.1" />
      <path
        d="M2.3 8.5h12.4 M8.5 2.3v12.4"
        stroke="var(--secondary)"
        strokeWidth="1"
        strokeOpacity={0.7}
      />
      <path
        d="M8.5 2.3c2.6 1.9 2.6 10.5 0 12.4 M8.5 2.3c-2.6 1.9-2.6 10.5 0 12.4"
        stroke="var(--secondary)"
        strokeWidth="1"
        strokeOpacity={0.7}
      />
    </svg>
  )
}

const PP_ICON: Record<keyof SnapshotIdentity, () => React.ReactElement> = {
  sector: SectorIcon,
  industry: IndustryIcon,
  country: CountryIcon,
}

// ── Metric gauges ─────────────────────────────────────────────────────────────

/** 270° radial arc; `fill` ∈ [0,1] of the sweep. Pure visual (no value text —
 *  the figure lives in the adjacent SourcedNumber). */
function RadialArc({ fill }: { fill: number }): React.ReactElement {
  const ARC_LEN = 103.67 // 2π·22·(270/360)
  const dash = clamp01(fill) * ARC_LEN
  const d = 'M 16.69 47.31 A 22 22 0 1 1 47.31 47.31'
  return (
    <svg
      width="60"
      height="60"
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      style={{ flex: 'none' }}
    >
      <path d={d} fill="none" stroke="var(--border-grid)" strokeWidth="6" strokeLinecap="round" />
      <path
        d={d}
        fill="none"
        stroke="var(--accent-cyan)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${ARC_LEN}`}
        style={{
          filter: 'drop-shadow(0 0 5px color-mix(in srgb, var(--accent-cyan) 55%, transparent))',
        }}
      />
    </svg>
  )
}

/** Horizontal 0–2 risk scale with a glowing marker at `value` (clamped to the
 *  rail). Market reference (β=1.0) is a dashed midpoint. */
function BetaScale({ value }: { value: number }): React.ReactElement {
  const x = 6 + clamp01(value / 2) * 208
  return (
    <svg
      width="100%"
      height="30"
      viewBox="0 0 220 30"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <line x1="6" y1="14" x2="214" y2="14" stroke="var(--border-grid)" strokeWidth="2" />
      <line
        x1="110"
        y1="7"
        x2="110"
        y2="21"
        stroke="var(--border-soft)"
        strokeWidth="1.2"
        strokeDasharray="2 2"
      />
      <line x1="6" y1="10" x2="6" y2="18" stroke="var(--text-dim)" strokeWidth="1.2" />
      <line x1="214" y1="10" x2="214" y2="18" stroke="var(--text-dim)" strokeWidth="1.2" />
      <circle cx={x} cy="14" r="8" fill="var(--primary)" fillOpacity={0.18} />
      <circle
        cx={x}
        cy="14"
        r="4.4"
        fill="var(--primary)"
        style={{
          filter: 'drop-shadow(0 0 7px color-mix(in srgb, var(--primary) 90%, transparent))',
        }}
      />
      <text x="6" y="28" fontFamily="var(--font-mono)" fontSize="8" fill="var(--text-dim)">
        0.0
      </text>
      <text x="103" y="28" fontFamily="var(--font-mono)" fontSize="8" fill="var(--text-muted)">
        1.0
      </text>
      <text x="203" y="28" fontFamily="var(--font-mono)" fontSize="8" fill="var(--text-dim)">
        2.0
      </text>
    </svg>
  )
}

/** Three ascending (or descending, for negative growth) bars + a trend arrow.
 *  A directional glyph, not a precise per-bar encoding. */
function TrendGlyph({ up }: { up: boolean }): React.ReactElement {
  const stroke = up ? 'var(--secondary)' : 'var(--danger)'
  const arrow = up ? 'var(--accent-cyan)' : 'var(--danger)'
  const ys = up ? [34, 26, 16] : [16, 26, 34]
  const hs = up ? [16, 24, 34] : [34, 24, 16]
  const path = up ? 'M10 32 L29 22 L47 11' : 'M10 11 L29 22 L47 32'
  const head = up ? 'M47 11 L41 11.5 M47 11 L46.2 17' : 'M47 32 L41 31.5 M47 32 L46.2 26'
  return (
    <svg
      width="58"
      height="56"
      viewBox="0 0 62 56"
      fill="none"
      aria-hidden="true"
      style={{ flex: 'none' }}
    >
      <line x1="4" y1="50" x2="58" y2="50" stroke="var(--border-grid)" strokeWidth="1" />
      {[8, 24, 40].map((x, i) => (
        <rect
          key={x}
          x={x}
          y={ys[i]}
          width="11"
          height={hs[i]}
          rx="1.5"
          fill={stroke}
          fillOpacity={0.3 + i * 0.12}
          stroke={stroke}
          strokeWidth="1"
          strokeOpacity={0.6}
        />
      ))}
      <path
        d={path}
        stroke={arrow}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeOpacity={0.9}
      />
      <path d={head} stroke={arrow} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

/** Scale-ladder + filled column — a decorative "market value" glyph (market cap
 *  has no natural 0–100 bound, so this is iconographic, not a precise encoding). */
function ScaleLadder(): React.ReactElement {
  return (
    <svg
      width="38"
      height="56"
      viewBox="0 0 40 56"
      fill="none"
      aria-hidden="true"
      style={{ flex: 'none' }}
    >
      <g stroke="var(--border-soft)" strokeWidth="1">
        <line x1="6" y1="6" x2="14" y2="6" />
        <line x1="6" y1="16" x2="11" y2="16" />
        <line x1="6" y1="26" x2="14" y2="26" />
        <line x1="6" y1="36" x2="11" y2="36" />
        <line x1="6" y1="46" x2="14" y2="46" />
      </g>
      <line x1="6" y1="2" x2="6" y2="50" stroke="var(--border-soft)" strokeWidth="1" />
      <rect x="20" y="6" width="14" height="44" rx="2" fill="var(--primary)" fillOpacity={0.28} />
      <rect
        x="20"
        y="6"
        width="14"
        height="44"
        rx="2"
        stroke="var(--primary)"
        strokeWidth="1"
        strokeOpacity={0.5}
      />
      <line x1="18" y1="9" x2="36" y2="9" stroke="var(--accent-cyan)" strokeWidth="1.4" />
    </svg>
  )
}

// ── Tile ──────────────────────────────────────────────────────────────────────

const TILE_GAUGE: Record<MetricKind, (m: SnapshotMetric) => ReactNode> = {
  market_cap: () => <ScaleLadder />,
  gross_margin: (m) => <RadialArc fill={m.raw} />,
  operating_margin: (m) => <RadialArc fill={m.raw} />,
  cagr: (m) => <TrendGlyph up={m.raw >= 0} />,
  beta: () => null, // beta renders its scale full-width below the figure
}

function TILE_FOOT(m: SnapshotMetric): string {
  switch (m.kind) {
    case 'market_cap':
      return 'MARKET VALUE'
    case 'gross_margin':
      return 'SCALE · 0 — 100%'
    case 'operating_margin':
      return 'EBIT MARGIN'
    case 'cagr':
      return 'TRAILING REVENUE'
    case 'beta':
      return betaDescriptor(m.raw)
  }
}

const tileBase: React.CSSProperties = {
  position: 'relative',
  background: 'var(--bg-card)',
  border: '1px solid var(--border-grid)',
  borderRadius: 'var(--radius-sm)',
  padding: '18px 18px 16px',
  minHeight: 168,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
}
const tileKey: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  letterSpacing: '0.2em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
}
const tileVal: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontWeight: 700,
  fontSize: 25,
  lineHeight: 1,
  letterSpacing: '0.01em',
  color: 'var(--text-primary)',
  fontVariantNumeric: 'tabular-nums',
}
const tileFoot: React.CSSProperties = {
  position: 'relative',
  marginTop: 12,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-dim)',
}

function TelemetryTile({
  metric,
  idx,
}: {
  metric: SnapshotMetric
  idx: number
}): React.ReactElement {
  const isBeta = metric.kind === 'beta'
  const figure = (
    <div style={tileVal}>
      <SourcedNumber value={metric.value} source={metric.source} />
    </div>
  )
  return (
    <article style={tileBase}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 'auto',
        }}
      >
        <span style={tileKey}>{metric.label}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>
          {`T0${idx + 1}`}
        </span>
      </div>

      {isBeta ? (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {figure}
          <BetaScale value={metric.raw} />
        </div>
      ) : (
        <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 14 }}>
          {TILE_GAUGE[metric.kind](metric)}
          {figure}
        </div>
      )}

      <div style={tileFoot}>{TILE_FOOT(metric)}</div>
    </article>
  )
}

// ── Passport ──────────────────────────────────────────────────────────────────

const ppCell: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '15px 22px',
  minWidth: 0,
}
const ppIco: React.CSSProperties = {
  flex: 'none',
  width: 34,
  height: 34,
  borderRadius: 8,
  border: '1px solid var(--border-soft)',
  background: 'color-mix(in srgb, var(--bg-elevated) 70%, transparent)',
  display: 'grid',
  placeItems: 'center',
}
const ppKey: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  letterSpacing: '0.22em',
  textTransform: 'uppercase',
  color: 'var(--text-dim)',
}
const ppVal: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontWeight: 500,
  fontSize: 14,
  color: 'var(--text-primary)',
  letterSpacing: '0.01em',
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}

function PassportCell({
  icon,
  label,
  value,
  withDivider,
}: {
  icon: ReactNode
  label: string
  value: string
  withDivider: boolean
}): React.ReactElement {
  return (
    <div
      style={{
        ...ppCell,
        ...(withDivider ? { borderLeft: '1px solid var(--border-grid)' } : null),
      }}
    >
      <div style={ppIco}>{icon}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
        <span style={ppKey}>{label}</span>
        <span style={ppVal}>{value}</span>
      </div>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CompanySnapshot({
  identity,
  metrics,
  quoteCurrency,
  fetchedAt,
  labels,
}: CompanySnapshotProps & {
  /** Localised passport keys, supplied by the chapter (Sector/Industry/Country). */
  labels: { sector: string; industry: string; country: string }
}): React.ReactElement | null {
  const passport: Array<{ key: keyof SnapshotIdentity; label: string; value: string }> = []
  if (identity.sector)
    passport.push({ key: 'sector', label: labels.sector, value: identity.sector })
  if (identity.industry)
    passport.push({ key: 'industry', label: labels.industry, value: identity.industry })
  if (identity.country)
    passport.push({ key: 'country', label: labels.country, value: identity.country })

  if (passport.length === 0 && metrics.length === 0) return null

  const asOf = isoDate(fetchedAt)
  // Discreet provenance hairline only — the cover already introduced the ticker,
  // so this content panel must NOT restate it as a hero. We carry just the
  // low-key quote-currency / as-of cluster (no ticker glyph, no big symbol).
  const showHeader = !!quoteCurrency || !!asOf

  return (
    <div
      style={{
        position: 'relative',
        background:
          'linear-gradient(180deg, color-mix(in srgb, var(--bg-elevated) 92%, transparent), var(--bg-card))',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-sm)',
        overflow: 'hidden',
        margin: '16px 0',
        boxShadow: '0 0 60px -34px color-mix(in srgb, var(--primary) 50%, transparent)',
      }}
    >
      {/* top hairline accent */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 1,
          background:
            'linear-gradient(90deg, transparent, color-mix(in srgb, var(--primary) 70%, transparent) 24%, color-mix(in srgb, var(--secondary) 60%, transparent) 62%, transparent)',
        }}
      />

      {/* discreet provenance hairline — deliberately low-key, never a hero. Just
          a right-aligned quote-currency / as-of cluster (the cover already owns
          the ticker), set in dim micro-mono above the passport strip. */}
      {showHeader && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 9,
            padding: '11px 22px 10px',
            borderBottom: '1px solid var(--border-grid)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: 'var(--text-dim)',
          }}
        >
          <span
            style={{
              width: 4,
              height: 4,
              borderRadius: '50%',
              background: 'var(--border-soft)',
              flex: 'none',
            }}
          />
          {quoteCurrency && (
            <span style={{ color: 'var(--text-muted)' }}>{`QUOTE · ${quoteCurrency}`}</span>
          )}
          {quoteCurrency && asOf && (
            <span style={{ width: 1, height: 9, background: 'var(--border-soft)', flex: 'none' }} />
          )}
          {asOf && <span>{`AS OF ${asOf}`}</span>}
        </div>
      )}

      {/* passport: classification identity (plain strings, no provenance) */}
      {passport.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'stretch',
            flexWrap: 'wrap',
            background: 'color-mix(in srgb, var(--bg-deep) 50%, transparent)',
          }}
        >
          {passport.map((p, i) => {
            const Icon = PP_ICON[p.key]
            return (
              <PassportCell
                key={p.key}
                icon={<Icon />}
                label={p.label}
                value={p.value}
                withDivider={i > 0}
              />
            )
          })}
        </div>
      )}

      {/* telemetry tiles: quantitative metrics, each with a value-encoding gauge */}
      {metrics.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${Math.min(metrics.length, 5)}, 1fr)`,
            gap: 1,
            background: 'var(--border-grid)',
            borderTop: passport.length > 0 ? '1px solid var(--border-grid)' : undefined,
          }}
        >
          {metrics.map((m, i) => (
            <TelemetryTile key={m.kind} metric={m} idx={i} />
          ))}
        </div>
      )}
    </div>
  )
}
