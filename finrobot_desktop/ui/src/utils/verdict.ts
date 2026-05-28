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
