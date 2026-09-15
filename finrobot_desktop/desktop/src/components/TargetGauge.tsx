// TargetGauge — analyst price-target gauge: a diverging bar anchored on the
// CURRENT price (the centre "now" tick), with the thesis target marked left
// (below → red) or right (above → green) of it. One dense row: label · track ·
// target value. It shows what a bare `$target` number can't — the DIRECTION and
// (clamped) MAGNITUDE of the gap at a glance.
//
// This is deliberately NOT TargetRange: TargetRange draws a confidence-scaled
// BAND, which requires a confidence tier the workspace summary (and the Coverage
// row) don't carry. Fabricating a band from a default tier would invent a false
// precision. TargetGauge shows ONLY the target + price direction — no band, no
// fabricated uncertainty. That honesty distinction is the point.
//
// The target stays SourcedNumber-wrapped (provenance popover) when a source is
// supplied. Omitted whenever the data can't honestly back it (no stored target,
// no current price) so names without a thesis target render nothing rather than a
// broken bar. var(--*) only; mono digits; 涨绿跌红; no animation.

import { useI18n } from '../i18n'
import { formatCurrency } from '../utils/format'
import { SourcedNumber, type NumberSource } from './SourcedNumber'

interface TargetGaugeProps {
  /** The thesis price target. null ⇒ nothing to plot → renders null. */
  targetPrice: number | null
  /** The current price the gap is read against (centre "now" tick). null /
   *  non-positive ⇒ no honest anchor → renders null. PREFER a live quote; an
   *  artifact's entry-at-creation price is a degraded fallback (a stale anchor
   *  mislabels the gap if price has moved). */
  currentPrice: number | null
  quoteCurrency: string
  /** Provenance for the target value's SourcedNumber popover. Absent ⇒ the value
   *  renders plain (still honest) — the workspace summary carries no per-number
   *  source, so the target there is plain; Coverage rides its upside source. */
  source?: NumberSource
  /** Pre-computed signed gap (target/price − 1) when the caller owns the
   *  canonical formula (Coverage's backend upside_to_target_live). Omitted ⇒
   *  derive a direct ratio. */
  upside?: number | null
  /** Ticker for the SourcedNumber deep-link (falls back to the route param). */
  ticker?: string
}

export function TargetGauge({
  targetPrice,
  currentPrice,
  quoteCurrency,
  source,
  upside,
  ticker,
}: TargetGaugeProps): React.ReactElement | null {
  const { t, locale } = useI18n()
  if (currentPrice == null || targetPrice == null || currentPrice <= 0) return null
  // Signed gap to target. Prefer the caller's canonical upside (Coverage owns the
  // backend formula); fall back to a direct ratio only if it's absent.
  const gap = upside != null ? upside : targetPrice / currentPrice - 1
  const up = gap >= 0
  const tone = up ? 'var(--success)' : 'var(--danger)'
  // The target marker's offset from the centre tick, as a fraction of each half
  // of the track. Clamp the magnitude at 50% so a moon-shot target still renders
  // a bounded bar (the exact figure rides the label + popover, not the geometry).
  const frac = Math.min(Math.abs(gap), 0.5) / 0.5
  // Centre = 50%; target sits left (below) or right (above) of it.
  const targetPct = up ? 50 + frac * 50 : 50 - frac * 50
  const fillLeft = up ? 50 : targetPct
  const fillWidth = Math.abs(targetPct - 50)

  return (
    <div className="target-gauge" aria-hidden={false}>
      <span className="target-gauge__label">{t('coverage.card.target')}</span>
      <span className="target-gauge__track">
        <span
          className="target-gauge__fill"
          style={{ left: `${fillLeft}%`, width: `${fillWidth}%`, background: tone }}
        />
        <span className="target-gauge__now" />
        <span
          className="target-gauge__mark"
          style={{ left: `${targetPct}%`, background: tone, boxShadow: `0 0 8px ${tone}` }}
        />
      </span>
      <span className="target-gauge__value" style={{ color: tone }}>
        <SourcedNumber
          className="coverage-source-number"
          value={targetPrice}
          source={source}
          ticker={ticker}
          format={(v) => formatCurrency(v, quoteCurrency, locale)}
        />
      </span>
    </div>
  )
}
