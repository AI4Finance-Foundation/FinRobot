// Reverse-DCF withheld-target headline (the "verdict", not a probe).
//
// Rendered under the cover verdict badge whenever the POINT target is withheld
// (price_target===null && market_implied!=null) — the directional verdict still
// stands. It turns a blank "target withheld" into the analyst's real question —
// "what is the market actually pricing in, and can a cash-flow model defend
// it?" — using the reverse-DCF figures already frozen into the artifact
// (market_implied + the dcf method range), never an LLM restatement.
//
// Two regimes, from MarketImpliedCheck:
//   • reachable  (implied_growth present): the gap ruler bridges DCF mid → market
//     with the implied annual growth as the bridge label (amber / --warning).
//   • unreachable (growth_unreachable): even the solver's max growth tops out
//     below the market — an option-value stock (red / --danger), ceiling capped.
//
// Visual language = design-A "gap ruler" lead + design-B three-anchor row as a
// SECONDARY info strip below the headline. Persistent state ⇒ STATIC neon halos
// only (no >1s animation, cosmic spec §7). Numbers are --font-mono tabular-nums;
// the big lede is --font-display; narrative is --font-body. cyan is reserved for
// the LIVE market price; implied growth / DCF figures are computed, never cyan.

import { useLayoutEffect, useRef, useState } from 'react'

import { useI18n } from '../../../i18n'
import { formatCurrency } from '../../../utils/format'
import type { DcfShape, ValuationMethodShape } from './types'

interface ReverseDcfHeadlineProps {
  marketImplied: NonNullable<DcfShape['market_implied']>
  /** The dcf method range from valuation_synthesis.methods (name==='dcf'). When
   * the target is withheld financial_modeling.implied_price is null, so the
   * "cash-flow model ceiling" MUST come from this method mid, not implied_price. */
  dcfMethod: ValuationMethodShape | null
  /** valuation_synthesis.current_price — the live pricing anchor (cyan-eligible). */
  currentPrice: number | null
  quoteCurrency: string
  /** valuation_synthesis target band (confidence-widened). Drives the fair-value
   * band shown in the right column — the one the cover's standalone <TargetRange>
   * used to draw before it was suppressed here to kill the duplicate. Falls back
   * to the dcf method range when the synthesis didn't ship an explicit band. */
  targetLow?: number | null
  targetHigh?: number | null
}

// ── log-scale ruler geometry ────────────────────────────────────────────────
// A log scale so a ~$40 DCF band and a ~$392 market anchor are both legible
// while the ~10× gap stays the dominant visual. Bounds are derived from the
// actual points (not hardcoded) so any ticker/price renders correctly.
//
// The ruler renders at TRUE PIXEL scale: the wrapper is measured (ResizeObserver)
// and the viewBox is set to that exact size, so the chart fills the column's full
// HEIGHT regardless of its width, and SVG font sizes are real px — a fixed-aspect
// viewBox previously tied height to width, so a narrower column also shortened
// the chart and left dead space under it.
const RULER_FALLBACK = { w: 280, h: 520 } as const

function useRulerSize(): [React.RefObject<HTMLDivElement | null>, { w: number; h: number }] {
  const ref = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState<{ w: number; h: number }>(RULER_FALLBACK)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = (): void => {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.height > 0) {
        setDims((prev) => {
          const w = Math.round(r.width)
          const h = Math.round(r.height)
          return prev.w === w && prev.h === h ? prev : { w, h }
        })
      }
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, dims]
}

interface Scale {
  y: (v: number) => number
  vMin: number
  vMax: number
  ticks: number[]
}

function buildScale(values: number[], top: number, bottom: number): Scale {
  const positive = values.filter((v) => v > 0)
  const lo = Math.min(...positive)
  const hi = Math.max(...positive)
  // Pad the log range ~12% each side so end markers aren't flush to the axis.
  const lnLo = Math.log(lo)
  const lnHi = Math.log(hi)
  const padded = (lnHi - lnLo) * 0.12 || 0.3
  const vMin = Math.exp(lnLo - padded)
  const vMax = Math.exp(lnHi + padded)
  const lnMin = Math.log(vMin)
  const lnMax = Math.log(vMax)
  const span = lnMax - lnMin || 1
  const y = (v: number): number => {
    const clamped = Math.max(vMin, Math.min(vMax, v))
    return top + (1 - (Math.log(clamped) - lnMin) / span) * (bottom - top)
  }
  // Nice 1-2-5 decade gridlines inside [vMin, vMax].
  const ticks: number[] = []
  const startExp = Math.floor(Math.log10(vMin))
  const endExp = Math.ceil(Math.log10(vMax))
  for (let e = startExp; e <= endExp; e += 1) {
    for (const m of [1, 2, 5]) {
      const t = m * 10 ** e
      if (t >= vMin && t <= vMax) ticks.push(t)
    }
  }
  return { y, vMin, vMax, ticks }
}

function fmtTick(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(v % 1000 === 0 ? 0 : 1)}k` : `${v}`
}

// ── credibility badge (design-B ✓ / ⚠ / ✗ / ● live) ─────────────────────────
type BadgeKind = 'warn' | 'ok' | 'live' | 'danger'

function CredBadge({ kind, text }: { kind: BadgeKind; text: string }): React.ReactElement {
  const palette: Record<BadgeKind, { fg: string; bg: string; border: string }> = {
    warn: {
      fg: 'var(--warning)',
      bg: 'var(--warning-soft)',
      border: 'color-mix(in srgb, var(--warning) 36%, transparent)',
    },
    ok: {
      fg: 'var(--success)',
      bg: 'var(--success-soft)',
      border: 'color-mix(in srgb, var(--success) 36%, transparent)',
    },
    live: {
      fg: 'var(--accent-cyan)',
      bg: 'var(--accent-cyan-soft)',
      border: 'var(--border-cyan-soft)',
    },
    danger: {
      fg: 'var(--danger)',
      bg: 'var(--danger-soft)',
      border: 'color-mix(in srgb, var(--danger) 40%, transparent)',
    },
  }
  const p = palette[kind]
  return (
    <span
      style={{
        marginLeft: 'auto',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 7px 2px 5px',
        borderRadius: 'var(--radius-pill)',
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        letterSpacing: '0.02em',
        whiteSpace: 'nowrap',
        color: p.fg,
        background: p.bg,
        border: `1px solid ${p.border}`,
      }}
    >
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" aria-hidden>
        {kind === 'ok' && (
          <path
            d="M4.5 12.5 9.5 17.5 19.5 6.5"
            stroke="currentColor"
            strokeWidth="2.1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {kind === 'warn' && (
          <>
            <path
              d="M12 3 2.5 20h19L12 3Z"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinejoin="round"
            />
            <path d="M12 10v4.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <circle cx="12" cy="17.4" r="1.05" fill="currentColor" />
          </>
        )}
        {kind === 'danger' && (
          <>
            <circle cx="12" cy="12" r="8.4" stroke="currentColor" strokeWidth="1.7" />
            <path
              d="M6.2 6.2 17.8 17.8"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </>
        )}
        {kind === 'live' && (
          <>
            <circle cx="12" cy="12" r="5" fill="currentColor" />
            <circle
              cx="12"
              cy="12"
              r="9"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeOpacity="0.5"
            />
          </>
        )}
      </svg>
      {text}
    </span>
  )
}

// ── one anchor chip (design-B AnchorCard, compacted to a secondary info row) ──
interface AnchorChipProps {
  index: string
  label: string
  badge: { kind: BadgeKind; text: string }
  value: string
  unit?: string
  sub: string
  accentRail: string
  valueColor: string
  valueGlow?: string
  multiple?: string
  multipleColor?: string
  multipleGlow?: string
}

function AnchorChip({
  index,
  label,
  badge,
  value,
  unit,
  sub,
  accentRail,
  valueColor,
  valueGlow,
  multiple,
  multipleColor,
  multipleGlow,
}: AnchorChipProps): React.ReactElement {
  return (
    <div
      style={{
        position: 'relative',
        padding: '13px 13px 14px',
        borderRadius: 'var(--radius-md)',
        background: 'linear-gradient(165deg, rgba(148,163,184,0.04), var(--bg-card-50))',
        border: '1px solid var(--border-faint)',
        boxShadow: `inset 3px 0 0 ${accentRail}`,
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          // Let the badge wrap onto its own row when the chip is narrow — an
          // unwrappable nowrap badge is what made adjacent chips collide.
          flexWrap: 'wrap',
          gap: 7,
          rowGap: 4,
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
          marginBottom: 8,
        }}
      >
        <span style={{ color: 'var(--text-dim)' }}>{index}</span>
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            minWidth: 0,
            flex: '1 1 auto',
          }}
        >
          {label}
        </span>
        <CredBadge kind={badge.kind} text={badge.text} />
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontVariantNumeric: 'tabular-nums',
          fontSize: 'clamp(18px, 3.2cqi, 24px)',
          fontWeight: 600,
          lineHeight: 1,
          color: valueColor,
          textShadow: valueGlow,
          display: 'flex',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          gap: 4,
          minWidth: 0,
        }}
      >
        {value}
        {unit && (
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-muted)' }}>{unit}</span>
        )}
      </div>
      {multiple && (
        <span
          style={{
            alignSelf: 'flex-start',
            marginTop: 8,
            padding: '3px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'color-mix(in srgb, var(--accent-cyan) 7%, transparent)',
            border: '1px solid var(--border-cyan-soft)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            fontWeight: 700,
            color: multipleColor,
            textShadow: multipleGlow ? `0 0 12px ${multipleGlow}` : undefined,
          }}
        >
          {multiple}
        </span>
      )}
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          lineHeight: 1.5,
          color: 'var(--text-dim)',
          marginTop: 8,
        }}
      >
        {sub}
      </div>
    </div>
  )
}

export function ReverseDcfHeadline({
  marketImplied: mi,
  dcfMethod,
  currentPrice,
  quoteCurrency,
  targetLow = null,
  targetHigh = null,
}: ReverseDcfHeadlineProps): React.ReactElement | null {
  const { t, locale } = useI18n()
  const [rulerRef, { w: rw, h: rh }] = useRulerSize()

  const unreachable = mi.growth_unreachable
  const cur = (n: number): string => formatCurrency(n, quoteCurrency, locale, 2)

  // The cash-flow ceiling the headline contrasts against the market:
  //   reachable  → the DCF method mid (the most the model stands on)
  //   unreachable→ ceiling_price (the most the model reaches at growth_ceiling)
  const dcfMid = dcfMethod?.mid ?? null
  const ceilingValue = unreachable ? (mi.ceiling_price ?? null) : dcfMid
  const market = currentPrice

  // Not enough to draw the contrast → render nothing (cover falls back to its
  // existing withheld one-liner). Both regimes need a ceiling + a market price.
  if (ceilingValue == null || market == null || ceilingValue <= 0 || market <= 0) return null

  const multiple = market / ceilingValue
  // "10×" reads cleaner than "9.8×" near round multiples; keep one decimal below 10.
  const multipleLabel = multiple >= 9.5 ? `${Math.round(multiple)}×` : `${multiple.toFixed(1)}×`

  const accent = unreachable ? 'var(--danger)' : 'var(--warning)'
  const accentSoft = unreachable ? 'var(--danger-soft)' : 'var(--warning-soft)'
  const accentGlow = unreachable ? 'var(--danger-glow)' : 'var(--warning-glow)'

  // ── ruler points ──────────────────────────────────────────────────────────
  const rulerTop = 18
  const rulerBottom = rh - 30
  const spineX = Math.round(Math.min(96, Math.max(60, rw * 0.32)))
  const rulerVals: number[] = [market, ceilingValue]
  if (!unreachable && dcfMethod) rulerVals.push(dcfMethod.low, dcfMethod.high)
  const scale = buildScale(rulerVals, rulerTop, rulerBottom)
  const yMarket = scale.y(market)
  const yCeil = scale.y(ceilingValue)

  const growthPct =
    !unreachable && mi.implied_growth != null ? `${(mi.implied_growth * 100).toFixed(1)}%` : null
  const ceilingGrowthPct =
    mi.growth_ceiling != null ? `${(mi.growth_ceiling * 100).toFixed(0)}%` : null
  const horizon = `${mi.horizon_years}y`

  // Fair-value band for the right column — the synthesis target band when the
  // backend shipped one (already confidence-widened), else the dcf method range.
  // This is the band the cover's standalone <TargetRange> used to draw; it now
  // lives here so the live price + band appear once, in one place. Reachable
  // only (an unreachable name has no defensible cash-flow band to plot).
  const fvLow = targetLow ?? dcfMethod?.low ?? null
  const fvHigh = targetHigh ?? dcfMethod?.high ?? null
  const fvMid = dcfMid ?? (fvLow != null && fvHigh != null ? (fvLow + fvHigh) / 2 : null)
  const showFvBand = !unreachable && fvLow != null && fvHigh != null && fvHigh > fvLow

  return (
    <section
      data-testid="reverse-dcf-headline"
      data-regime={unreachable ? 'unreachable' : 'reachable'}
      style={{
        display: 'grid',
        // Left ruler takes ~30% of whatever width the chapter gives us, bounded
        // [216, 320] — a fixed 340px previously ate >half of a ~600px panel and
        // crushed the right column until the anchor chips overlapped. The section
        // is an inline-size container so children scale type with cqi units.
        gridTemplateColumns: 'clamp(216px, 30%, 320px) minmax(0, 1fr)',
        containerType: 'inline-size',
        gap: 0,
        marginTop: 18,
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        background:
          'linear-gradient(160deg, color-mix(in srgb, var(--primary) 5%, transparent), var(--bg-card-overlay))',
        border: '1px solid var(--border-soft)',
        // persistent withheld-target state → STATIC halo (no breathing/animation)
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.04), 0 0 0 1px ${accentSoft}, 0 0 48px -14px ${accentGlow}`,
        position: 'relative',
      }}
    >
      {/* ── LEFT: the vertical valuation gap ruler (lead visual) ── */}
      <div
        style={{
          position: 'relative',
          padding: '22px 20px 18px',
          borderRight: '1px solid var(--border-faint)',
          background: `radial-gradient(120% 60% at 50% ${unreachable ? '70%' : '40%'}, ${accentSoft}, transparent 62%), var(--surface-panel-50)`,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: 10,
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 12,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--text-secondary)',
            }}
          >
            {t('chapter.cover.reverseDcf.scaleTitle')}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9.5,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-dim)',
            }}
          >
            {t('chapter.cover.reverseDcf.scaleUnit')}
          </span>
        </div>

        {/* measured wrapper: the svg fills the column's remaining height; the
            viewBox mirrors the measured px box so 1 svg unit === 1 css px (no
            aspect-locked shrinking, no scaled-down text). */}
        <div ref={rulerRef} style={{ flex: 1, minHeight: 420 }}>
          <svg
            viewBox={`0 0 ${rw} ${rh}`}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label={
              unreachable
                ? `Valuation ruler: even ${ceilingGrowthPct ?? 'max'} growth tops out at ${cur(ceilingValue)}, below the ${cur(market)} market`
                : `Valuation ruler: DCF reaches ${cur(ceilingValue)}, the market sits at ${cur(market)}`
            }
            style={{ display: 'block', width: '100%', height: '100%' }}
          >
            <defs>
              <linearGradient id="rdcf-gap" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accent} stopOpacity="0.3" />
                <stop offset="60%" stopColor={accent} stopOpacity="0.09" />
                <stop offset="100%" stopColor={accent} stopOpacity="0.03" />
              </linearGradient>
              <filter id="rdcf-cyan" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="3.2" result="b" />
                <feMerge>
                  <feMergeNode in="b" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <filter id="rdcf-accent" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="2.4" result="b" />
                <feMerge>
                  <feMergeNode in="b" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <marker
                id="rdcf-arrow"
                markerWidth="8"
                markerHeight="8"
                refX="4"
                refY="1.2"
                orient="auto"
                markerUnits="userSpaceOnUse"
              >
                <path d="M4 0 L7.5 6 L0.5 6 Z" fill={accent} />
              </marker>
            </defs>

            {/* spine + baseline */}
            <line
              x1={spineX}
              y1={rulerTop}
              x2={spineX}
              y2={rulerBottom}
              stroke="var(--border-soft)"
              strokeWidth="1"
            />
            <line
              x1={spineX - 12}
              y1={rulerBottom}
              x2={rw - 12}
              y2={rulerBottom}
              stroke="var(--border-soft)"
              strokeWidth="1"
            />

            {/* log gridlines */}
            <g fontFamily="var(--font-mono)" fontSize="8" fill="var(--text-dim)">
              {scale.ticks.map((tk) => {
                const ty = scale.y(tk)
                return (
                  <g key={tk}>
                    <line
                      x1={spineX - 6}
                      y1={ty}
                      x2={spineX}
                      y2={ty}
                      stroke="var(--border-faint)"
                    />
                    <text x={spineX - 9} y={ty + 2.6} textAnchor="end">
                      {fmtTick(tk)}
                    </text>
                  </g>
                )
              })}
            </g>

            {/* the gap fill between the ceiling and the market */}
            <rect
              x={spineX}
              y={yMarket}
              width={Math.max(0, rw - spineX - 54)}
              height={Math.max(0, yCeil - yMarket)}
              fill="url(#rdcf-gap)"
            />
            {/* gap measuring bracket */}
            <path
              d={`M${spineX} ${yCeil} L${spineX + 8} ${yCeil} M${spineX + 8} ${yCeil} L${spineX + 8} ${yMarket} M${spineX} ${yMarket} L${spineX + 8} ${yMarket}`}
              fill="none"
              stroke={accent}
              strokeWidth="1.4"
              strokeOpacity="0.85"
              markerEnd="url(#rdcf-arrow)"
            />

            {/* bridge annotation: what fills the gap (reachable = implied growth) */}
            <g transform={`translate(${spineX + 14} ${(yMarket + yCeil) / 2 - 14})`}>
              {growthPct ? (
                <>
                  <text
                    fontFamily="var(--font-mono)"
                    x="0"
                    y="0"
                    fontSize="19"
                    fontWeight="700"
                    fill={accent}
                    filter="url(#rdcf-accent)"
                  >
                    {growthPct}
                  </text>
                  <text
                    fontFamily="var(--font-mono)"
                    x="0"
                    y="14"
                    fontSize="9"
                    fill={accent}
                    opacity="0.9"
                  >
                    /yr · {horizon}
                  </text>
                  <text
                    fontFamily="var(--font-body)"
                    x="0"
                    y="30"
                    fontSize="8.5"
                    fill="var(--text-muted)"
                  >
                    {t('chapter.cover.reverseDcf.bridgeNote')}
                  </text>
                </>
              ) : (
                <>
                  <text fontFamily="var(--font-body)" x="0" y="0" fontSize="9" fill={accent}>
                    {t('chapter.cover.reverseDcf.short')}
                  </text>
                  <text
                    fontFamily="var(--font-body)"
                    x="0"
                    y="12"
                    fontSize="8.5"
                    fill="var(--text-muted)"
                  >
                    {ceilingGrowthPct ? `${ceilingGrowthPct}/yr · ${horizon}` : horizon}
                  </text>
                </>
              )}
            </g>

            {/* DCF mid marker on the gap axis — a single cash-flow point, NOT the
                boxed low–high range. The range lives once in the right-column
                fair-value band; the ruler's job is the spread (market line vs one
                cash-flow point), so a second range box here was the same numbers
                twice for exactly the single-method withheld reports this renders on. */}
            {!unreachable && dcfMethod && (
              <>
                <line
                  x1={spineX - 26}
                  y1={yCeil}
                  x2={spineX + 18}
                  y2={yCeil}
                  stroke="var(--text-secondary)"
                  strokeWidth="1.6"
                />
                <circle
                  cx={spineX}
                  cy={yCeil}
                  r="3"
                  fill="var(--text-secondary)"
                  stroke="var(--bg-card)"
                  strokeWidth="1"
                />
                <g transform={`translate(${spineX + 22} ${yCeil - 5})`}>
                  <text
                    fontFamily="var(--font-mono)"
                    x="0"
                    y="0"
                    fontSize="7.5"
                    letterSpacing="0.06em"
                    fill="var(--text-dim)"
                  >
                    {t('chapter.cover.reverseDcf.dcfMid')}
                  </text>
                  <text
                    fontFamily="var(--font-mono)"
                    x="0"
                    y="15"
                    fontSize="13"
                    fontWeight="600"
                    fill="var(--text-secondary)"
                  >
                    {cur(dcfMethod.mid)}
                  </text>
                </g>
              </>
            )}

            {/* unreachable: the whole column the model can ever climb */}
            {unreachable && (
              <>
                <rect
                  x={spineX - 10}
                  y={yCeil}
                  width={12}
                  height={Math.max(2, rulerBottom - yCeil)}
                  rx="2"
                  fill={accent}
                  fillOpacity="0.07"
                  stroke={accent}
                  strokeOpacity="0.25"
                  strokeWidth="1"
                />
                <line
                  x1={spineX - 26}
                  y1={yCeil}
                  x2={spineX + 18}
                  y2={yCeil}
                  stroke={accent}
                  strokeWidth="1.8"
                  filter="url(#rdcf-accent)"
                />
                <circle cx={spineX} cy={yCeil} r="4" fill={accent} filter="url(#rdcf-accent)" />
                <g transform={`translate(${spineX + 22} ${yCeil + 18})`}>
                  <text
                    fontFamily="var(--font-mono)"
                    x="0"
                    y="0"
                    fontSize="8"
                    letterSpacing="0.5"
                    fill={accent}
                  >
                    {ceilingGrowthPct ? `${ceilingGrowthPct}/yr × ${horizon}` : horizon}
                  </text>
                  <text
                    fontFamily="var(--font-mono)"
                    x="0"
                    y="18"
                    fontSize="14"
                    fontWeight="700"
                    fill="var(--text-primary)"
                    filter="url(#rdcf-accent)"
                  >
                    {cur(ceilingValue)}
                  </text>
                </g>
              </>
            )}

            {/* MARKET anchor (LIVE → cyan, the one cyan-eligible quantity) */}
            <line
              x1={spineX - 26}
              y1={yMarket}
              x2={rw - 60}
              y2={yMarket}
              stroke="var(--accent-cyan)"
              strokeWidth="1.8"
              filter="url(#rdcf-cyan)"
            />
            <circle
              cx={spineX}
              cy={yMarket}
              r="4"
              fill="var(--accent-cyan)"
              filter="url(#rdcf-cyan)"
            />
            <g transform={`translate(${spineX + 22} ${yMarket - 14})`}>
              <circle cx="3" cy="-3" r="2.6" fill="var(--accent-cyan)" filter="url(#rdcf-cyan)" />
              <text
                fontFamily="var(--font-mono)"
                x="11"
                y="0"
                fontSize="8.5"
                letterSpacing="0.08em"
                fill="var(--accent-cyan)"
              >
                {t('chapter.cover.reverseDcf.marketLive')}
              </text>
              <text
                fontFamily="var(--font-mono)"
                x="0"
                y="18"
                fontSize="15"
                fontWeight="700"
                fill="var(--accent-cyan)"
                filter="url(#rdcf-cyan)"
              >
                {cur(market)}
              </text>
            </g>
          </svg>
        </div>
      </div>

      {/* ── RIGHT: conclusion-first narrative + secondary anchor row ── */}
      <div
        style={{
          padding: 'clamp(16px, 3cqi, 24px) clamp(14px, 3cqi, 26px) 18px',
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
        }}
      >
        {/* the conclusion-first lede (verdict, not a probe) */}
        {unreachable ? (
          <p
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 500,
              fontSize: 'clamp(19px, 3.6cqi, 27px)',
              lineHeight: 1.24,
              letterSpacing: '0.2px',
              color: 'var(--text-primary)',
              margin: '0 0 18px',
            }}
          >
            {t('chapter.cover.reverseDcf.ledeB.pre')}{' '}
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: accent }}>
              {ceilingGrowthPct ?? '—'}
            </span>{' '}
            {t('chapter.cover.reverseDcf.ledeB.mid')}{' '}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                color: 'var(--text-primary)',
              }}
            >
              {horizon}
            </span>{' '}
            {t('chapter.cover.reverseDcf.ledeB.impliesOnly')}{' '}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                color: 'var(--text-primary)',
              }}
            >
              {cur(ceilingValue)}
            </span>{' '}
            {t('chapter.cover.reverseDcf.ledeB.marketAt')}{' '}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                color: 'var(--accent-cyan)',
              }}
            >
              {cur(market)}
            </span>
            .
          </p>
        ) : (
          <p
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 500,
              fontSize: 'clamp(20px, 4cqi, 30px)',
              lineHeight: 1.22,
              letterSpacing: '0.2px',
              color: 'var(--text-primary)',
              margin: '0 0 18px',
            }}
          >
            {t('chapter.cover.reverseDcf.ledeA.pre')}{' '}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                color: accent,
                whiteSpace: 'nowrap',
              }}
            >
              ~{growthPct}/yr
            </span>{' '}
            {t('chapter.cover.reverseDcf.ledeA.mid')}{' '}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                color: 'var(--text-primary)',
              }}
            >
              {horizon}
            </span>
            .
          </p>
        )}

        {/* ── secondary info row: design-B three anchors (implied ⚠ / ceiling ✓ /
             market ● live), visually subordinate to the lede above. These carry the
             same data language as the MarketImpliedPanel probe so the analyst reads
             them as data, while the lede + ruler above read as the verdict. ── */}
        <div
          style={{
            display: 'grid',
            // auto-fit instead of a hard 3-up: when the column can't give each
            // chip ~150px the chips WRAP to 2+1 / 1-col instead of overlapping.
            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
            gap: 10,
            marginBottom: 18,
          }}
        >
          {/* anchor 1 · market-implied growth (the bar the price assumes) */}
          <AnchorChip
            index="01"
            label={t('chapter.cover.reverseDcf.anchor.implied')}
            badge={
              unreachable
                ? { kind: 'danger', text: t('chapter.cover.reverseDcf.badge.unreachable') }
                : { kind: 'warn', text: t('chapter.cover.reverseDcf.badge.stretch') }
            }
            value={unreachable ? '—' : (growthPct ?? '—')}
            unit={unreachable ? undefined : '/yr'}
            sub={`${horizon}`}
            accentRail={accent}
            valueColor={accent}
          />
          {/* anchor 2 · cash-flow ceiling (the most a DCF can stand on) */}
          <AnchorChip
            index="02"
            label={t('chapter.cover.reverseDcf.anchor.ceiling')}
            badge={{ kind: 'ok', text: t('chapter.cover.reverseDcf.badge.defensible') }}
            value={cur(ceilingValue)}
            sub={
              unreachable
                ? t('chapter.cover.reverseDcf.atCeiling', { ceiling: ceilingGrowthPct ?? '—' })
                : t('chapter.cover.reverseDcf.dcfMidRange', {
                    range: dcfMethod ? `${cur(dcfMethod.low)}–${cur(dcfMethod.high)}` : '—',
                  })
            }
            accentRail="var(--success)"
            valueColor="var(--text-primary)"
          />
          {/* NOTE: the 3rd "pricing anchor" chip was deleted — it restated the
              LIVE price already plotted on the ruler (and formerly on the cover
              TargetRange). Live price now appears once, on the ruler. The gap
              multiple it carried moves into the framing footer below. */}
        </div>

        {/* fair-value band — the defensible cash-flow range, on its own price
            rail. Fills the column the deleted pricing-anchor chip used to, and
            restores the band the suppressed cover <TargetRange> carried. The
            point marker is the dcf mid; width = the synthesis band (already
            widened as confidence drops). No live tick here — the gap vs market
            is the ruler's job; this rail is "where cash flows defend". */}
        {showFvBand && fvLow != null && fvHigh != null && (
          <div style={{ marginBottom: 18 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 8,
                flexWrap: 'wrap',
                marginBottom: 7,
              }}
            >
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9.5,
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                  color: 'var(--text-muted)',
                }}
              >
                {t('chapter.cover.reverseDcf.fairValueBand')}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {cur(fvLow)} – {cur(fvHigh)}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  letterSpacing: '0.03em',
                  color: 'var(--text-dim)',
                }}
              >
                {t('chapter.cover.reverseDcf.bandWidensNote')}
              </span>
            </div>
            {(() => {
              const pad = (fvHigh - fvLow) * 0.12 || 1
              const vMin = fvLow - pad
              const span = fvHigh + pad - vMin || 1
              const px = (v: number): number => ((v - vMin) / span) * 100
              const midX = fvMid != null ? px(fvMid) : null
              return (
                <svg
                  viewBox="0 0 100 14"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label={`Cash-flow fair value ${cur(fvLow)} to ${cur(fvHigh)}`}
                  style={{ display: 'block', width: '100%', height: 14, overflow: 'visible' }}
                >
                  <line
                    x1="0"
                    y1="7"
                    x2="100"
                    y2="7"
                    stroke="var(--border-soft)"
                    strokeWidth="1"
                    vectorEffect="non-scaling-stroke"
                  />
                  <rect
                    x={px(fvLow)}
                    y="3.5"
                    width={Math.max(0.5, px(fvHigh) - px(fvLow))}
                    height="7"
                    rx="1"
                    fill="color-mix(in srgb, var(--success) 16%, transparent)"
                    stroke="color-mix(in srgb, var(--success) 42%, transparent)"
                    strokeWidth="0.6"
                    vectorEffect="non-scaling-stroke"
                  />
                  {midX != null && (
                    <line
                      x1={midX}
                      y1="1"
                      x2={midX}
                      y2="13"
                      stroke="var(--text-primary)"
                      strokeWidth="2"
                      vectorEffect="non-scaling-stroke"
                    />
                  )}
                </svg>
              )
            })()}
          </div>
        )}

        {/* the reframing footer — verdict-aware (reachable = discipline, B = optionality) */}
        <div
          style={{
            marginTop: 'auto',
            display: 'flex',
            gap: 12,
            padding: 14,
            borderRadius: 'var(--radius-md)',
            background: accentSoft,
            border: `1px solid ${accent}`,
            borderLeftWidth: 3,
          }}
        >
          <span style={{ flex: 'none', marginTop: 1 }}>
            {unreachable ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                <path d="M10 17 V11" stroke={accent} strokeWidth="1.5" strokeLinecap="round" />
                <path
                  d="M10 11 C10 7 6 7 6 4 M10 11 C10 7 14 7 14 4"
                  stroke={accent}
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  fill="none"
                />
                <circle cx="6" cy="3.2" r="1.6" fill={accent} />
                <circle cx="14" cy="3.2" r="1.6" fill={accent} />
                <circle cx="10" cy="17.4" r="1.6" fill={accent} />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                <path
                  d="M10 2 L16.5 4.4 V9.2 C16.5 13.4 13.6 16.3 10 17.6 C6.4 16.3 3.5 13.4 3.5 9.2 V4.4 Z"
                  stroke={accent}
                  strokeWidth="1.4"
                  fill={accentSoft}
                />
                <path
                  d="M6.8 9.8 L9 12 L13.2 7.4"
                  stroke={accent}
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 13,
              lineHeight: 1.5,
              color: 'var(--text-secondary)',
            }}
          >
            {unreachable ? (
              <>
                <b style={{ color: accent, fontWeight: 600 }}>
                  {t('chapter.cover.reverseDcf.optionalityTitle')}
                </b>{' '}
                {t('chapter.cover.reverseDcf.optionalityBody')}
              </>
            ) : (
              <>
                <b style={{ color: accent, fontWeight: 600 }}>
                  {t('chapter.cover.reverseDcf.withheldTitle')}
                </b>{' '}
                — {t('chapter.cover.reverseDcf.withheldBody', { multiple: multipleLabel })}
              </>
            )}
          </span>
        </div>
      </div>
    </section>
  )
}
