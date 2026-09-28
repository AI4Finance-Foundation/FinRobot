// TargetRange — a compact horizontal price ruler that replaces a bare
// `$target.toFixed(2)` headline number. It shows three things at once:
//   • the LIVE price tick (cyan — the one cyan-eligible quantity, cosmic spec)
//   • the POINT target tick, sitting AT the anchor method's value (NOT the
//     band midpoint — divergent methods anchor on one method, never a blend)
//   • the [target_low, target_high] band, whose WIDTH encodes confidence
//     (high = tight, very_low = wide) and which may be ASYMMETRIC around the
//     point.
//
// Withheld state (point target honestly null): render the band + live tick with
// NO point tick — the verdict still stands on direction, the precise number is
// withheld. The band then frames "where a defensible target would sit" without
// fabricating a false-precise point.
//
// Simple grid/bar → inline SVG (cosmic spec §6.5). Persistent → static neon
// only, no animation. Numbers are var(--font-mono) tabular-nums; var(--*) only.

import type { ConfidenceTier } from '../utils/verdict'
import { confidenceChip } from '../utils/verdict'
import { formatCurrency } from '../utils/format'
import { useI18n } from '../i18n'

interface TargetRangeProps {
  /** The headline point target. null ⇒ withheld → band renders without a point tick. */
  point: number | null
  /** Explicit band ends. When either is null the band is derived from the point
   *  + the confidence tier's bandFactor (a symmetric ± fraction of the point). */
  low?: number | null
  high?: number | null
  /** The live / snapshot price the verdict is measured against (cyan tick). */
  currentPrice: number | null
  /** Confidence tier — widens the derived band + dims the whole primitive on a
   *  NON-hue channel (never recolours the ticks). */
  confidence: ConfidenceTier
  quoteCurrency: string
  /** Method the point anchors on (e.g. "dcf" / "comps_pe") — shown as a caption
   *  so the analyst sees the point isn't a blended midpoint. */
  anchorMethod?: string | null
}

/** Resolve the [low, high] band: explicit ends win; otherwise derive a
 * confidence-scaled symmetric band around the point. In withheld mode (no
 * point) an explicit band is required — without it there is nothing to draw. */
function resolveBand(
  point: number | null,
  low: number | null | undefined,
  high: number | null | undefined,
  bandFactor: number,
): { lo: number; hi: number } | null {
  const lo = low ?? null
  const hi = high ?? null
  if (lo !== null && hi !== null && hi > lo) return { lo, hi }
  if (point !== null && point > 0) {
    // Derived band: ±(bandFactor·25%) of the point. high tier → ±6.25%,
    // very_low → ±25%. Asymmetric explicit ends override this entirely.
    const half = point * 0.25 * bandFactor
    return { lo: Math.max(0, point - half), hi: point + half }
  }
  return null
}

export function TargetRange({
  point,
  low,
  high,
  currentPrice,
  confidence,
  quoteCurrency,
  anchorMethod = null,
}: TargetRangeProps): React.ReactElement | null {
  const { locale, t } = useI18n()
  const chip = confidenceChip(confidence, locale)
  const band = resolveBand(point, low, high, chip.bandFactor)
  if (!band) return null

  // Domain spans the band, the point, and the live price, padded 8% each side so
  // ticks never sit flush to the rail end.
  const xs = [band.lo, band.hi]
  if (point !== null) xs.push(point)
  if (currentPrice !== null && currentPrice > 0) xs.push(currentPrice)
  const dMin = Math.min(...xs)
  const dMax = Math.max(...xs)
  const pad = (dMax - dMin || dMax || 1) * 0.08
  const vMin = dMin - pad
  const vMax = dMax + pad
  const span = vMax - vMin || 1
  // Percent position along the rail [0,100].
  const pos = (v: number): number => ((v - vMin) / span) * 100

  const cur = (n: number): string => formatCurrency(n, quoteCurrency, locale, 2)
  const bandLeft = pos(band.lo)
  const bandWidth = pos(band.hi) - bandLeft
  const withheld = point === null
  // In-band = the point is withheld BECAUSE the live price sits INSIDE the fair-value
  // band (range spans market) → fairly valued, a confident HOLD. Strict containment
  // mirrors the backend `_range_spans_market` AND matches the band visual the analyst
  // sees (the price tick inside the band box). Lead with the conclusion ("Fairly Valued"),
  // not the mechanic ("withheld"). Out-of-band withholds (genuine uncertainty — methods
  // one-sided / far from market) keep the honest "point target withheld" framing.
  const inFairValueBand =
    withheld &&
    currentPrice !== null &&
    currentPrice > 0 &&
    band.lo <= currentPrice &&
    currentPrice <= band.hi

  return (
    <div
      data-testid="target-range"
      data-withheld={withheld ? 'true' : 'false'}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minWidth: 200,
        opacity: chip.opacity,
      }}
    >
      {/* Header: the point (or withheld word) + anchor caption */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-muted)',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          {t(inFairValueBand ? 'targetRange.fairValueLabel' : 'targetRange.label')}
        </span>
        {withheld ? (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 14,
              fontWeight: 500,
              color: 'var(--text-secondary)',
            }}
          >
            {t(inFairValueBand ? 'targetRange.withinFairValue' : 'targetRange.withheld')}
          </span>
        ) : (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 22,
              fontWeight: 600,
              color: 'var(--text-primary)',
              fontVariantNumeric: 'tabular-nums',
              lineHeight: 1,
            }}
          >
            {cur(point)}
          </span>
        )}
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {cur(band.lo)} – {cur(band.hi)}
        </span>
        {anchorMethod && !withheld && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9.5,
              color: 'var(--text-dim)',
              letterSpacing: '0.04em',
            }}
          >
            {t('targetRange.anchoredOn', { method: anchorMethod.toUpperCase() })}
          </span>
        )}
      </div>

      {/* The rail: band rect + live tick + point tick. Static neon only. */}
      <svg
        viewBox="0 0 100 16"
        preserveAspectRatio="none"
        role="img"
        aria-label={
          withheld
            ? t('targetRange.ariaWithheld', { lo: cur(band.lo), hi: cur(band.hi) })
            : t('targetRange.aria', { point: cur(point), lo: cur(band.lo), hi: cur(band.hi) })
        }
        style={{ display: 'block', width: '100%', height: 16, overflow: 'visible' }}
      >
        {/* baseline rail */}
        <line
          x1="0"
          y1="8"
          x2="100"
          y2="8"
          stroke="var(--border-soft)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        {/* the confidence-scaled band */}
        <rect
          x={bandLeft}
          y="5"
          width={Math.max(0.5, bandWidth)}
          height="6"
          rx="1"
          fill="color-mix(in srgb, var(--primary) 22%, transparent)"
          stroke="color-mix(in srgb, var(--primary) 45%, transparent)"
          strokeWidth="0.6"
          vectorEffect="non-scaling-stroke"
          style={chip.glow !== 'none' ? { filter: `drop-shadow(${chip.glow})` } : undefined}
        />
        {/* live price tick (cyan — the one cyan-eligible quantity) */}
        {currentPrice !== null && currentPrice > 0 && (
          <line
            x1={pos(currentPrice)}
            y1="1"
            x2={pos(currentPrice)}
            y2="15"
            stroke="var(--accent-cyan)"
            strokeWidth="1.6"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {/* point target tick, AT the anchor (omitted when withheld) */}
        {!withheld && (
          <line
            x1={pos(point)}
            y1="1"
            x2={pos(point)}
            y2="15"
            stroke="var(--text-primary)"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      {/* legend: live vs target tick meaning */}
      <div
        style={{
          display: 'flex',
          gap: 14,
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          color: 'var(--text-muted)',
        }}
      >
        {currentPrice !== null && currentPrice > 0 && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 2, background: 'var(--accent-cyan)' }} aria-hidden />
            {t('targetRange.legendLive')} {cur(currentPrice)}
          </span>
        )}
        {!withheld && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 2, background: 'var(--text-primary)' }} aria-hidden />
            {t('targetRange.legendTarget')}
          </span>
        )}
      </div>
    </div>
  )
}
