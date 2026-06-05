// Verdict label helper — translates BUY/HOLD/SELL to Chinese 投行 standard
// terms in zh locale. English locale keeps the uppercase form per investment-
// bank report convention.
//
// Backend types remain the uppercase string union; we only localise at the
// display layer.

import { tSync, type Locale } from '../i18n'

// REVIEW is the data-health-gate verdict: the valuation methods failed
// cross-checks (spread > 50%), so no defensible directional call exists.
// It carries no price target and must NOT render in 涨绿跌红 — it's a
// neutral "withheld pending review" state.
export type Verdict = 'BUY' | 'HOLD' | 'SELL' | 'REVIEW'

/**
 * Translate a verdict for display. Pass an explicit locale to avoid hook usage
 * in non-React contexts. The default reads the current zustand snapshot.
 *
 *   verdictLabel('BUY')           → '买入' (when locale=zh) or 'BUY' (en)
 *   verdictLabel('HOLD', 'en')    → 'HOLD'
 *   verdictLabel('REVIEW')        → '待复核' (zh) or 'REVIEW' (en)
 *   verdictLabel(null)            → '—'
 */
export function verdictLabel(
  verdict: Verdict | string | null | undefined,
  locale?: Locale,
): string {
  if (!verdict) return '—'
  const upper = verdict.toUpperCase()
  if (upper !== 'BUY' && upper !== 'HOLD' && upper !== 'SELL' && upper !== 'REVIEW') return upper

  // Both locales go through the catalog:
  //   zh → '买入' / '持有' / '卖出' / '待复核' (中国券商 standard)
  //   en → 'BUY' / 'HOLD' / 'SELL' / 'REVIEW' (investment-bank uppercase convention)
  // The `locale` parameter is reserved for callers who explicitly need a
  // non-default locale; current store snapshot is used by default.
  void locale
  const key =
    upper === 'BUY'
      ? 'verdict.buy'
      : upper === 'HOLD'
        ? 'verdict.hold'
        : upper === 'SELL'
          ? 'verdict.sell'
          : 'verdict.review'
  return tSync(key)
}

/** Cosmic-theme tone (bg / fg / border) for a verdict badge. */
export interface VerdictTone {
  bg: string
  fg: string
  border: string
}

// Single source of truth for verdict colouring — consumed by the cover hero
// badge AND the right-rail version-timeline badge. REVIEW is deliberately a
// neutral slate (not 涨绿跌红): it makes no directional call, so colouring it
// like a buy/sell would misrepresent the withheld conclusion.
const VERDICT_TONE: Record<string, VerdictTone> = {
  BUY: {
    bg: 'var(--success-soft)',
    fg: 'var(--success)',
    border: 'color-mix(in srgb, var(--success) 55%, transparent)',
  },
  HOLD: {
    bg: 'var(--warning-soft)',
    fg: 'var(--warning)',
    border: 'color-mix(in srgb, var(--warning) 55%, transparent)',
  },
  SELL: {
    bg: 'var(--danger-soft)',
    fg: 'var(--danger)',
    border: 'color-mix(in srgb, var(--danger) 55%, transparent)',
  },
  REVIEW: {
    bg: 'var(--neutral-soft)',
    fg: 'var(--text-secondary)',
    border: 'var(--neutral-edge)',
  },
}

/** Resolve a verdict's badge tone; unknown / missing verdicts fall back to HOLD. */
export function verdictTone(verdict: Verdict | string | null | undefined): VerdictTone {
  const upper = (verdict ?? '').toUpperCase()
  return VERDICT_TONE[upper] ?? VERDICT_TONE.HOLD
}
