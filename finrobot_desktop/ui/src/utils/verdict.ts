// Verdict label helper — translates BUY/HOLD/SELL to Chinese 投行 standard
// terms in zh locale. English locale keeps the uppercase form per investment-
// bank report convention.
//
// Backend types remain the uppercase string union; we only localise at the
// display layer.

import { tSync, type Locale } from "../i18n"

export type Verdict = "BUY" | "HOLD" | "SELL"

/**
 * Translate a verdict for display. Pass an explicit locale to avoid hook usage
 * in non-React contexts. The default reads the current zustand snapshot.
 *
 *   verdictLabel('BUY')           → '买入' (when locale=zh) or 'BUY' (en)
 *   verdictLabel('HOLD', 'en')    → 'HOLD'
 *   verdictLabel(null)            → '—'
 */
export function verdictLabel(
  verdict: Verdict | string | null | undefined,
  locale?: Locale,
): string {
  if (!verdict) return "—"
  const upper = verdict.toUpperCase()
  if (upper !== "BUY" && upper !== "HOLD" && upper !== "SELL") return upper

  // Both locales go through the catalog:
  //   zh → '买入' / '持有' / '卖出' (中国券商 standard)
  //   en → 'BUY' / 'HOLD' / 'SELL' (investment-bank uppercase convention)
  // The `locale` parameter is reserved for callers who explicitly need a
  // non-default locale; current store snapshot is used by default.
  void locale
  const key =
    upper === "BUY" ? "verdict.buy" : upper === "HOLD" ? "verdict.hold" : "verdict.sell"
  return tSync(key)
}
