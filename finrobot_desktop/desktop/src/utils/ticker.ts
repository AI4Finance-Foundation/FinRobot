// Shared ticker-symbol helpers. Replaces the old stores/stocksStore.isValidTicker
// that was removed with the legacy /stocks landing. Kept deliberately small and
// dependency-free so both the Coverage hero search and any future ticker input
// (coverage add, CmdK) validate against ONE definition.

// 1–12 chars, upper-case letters/digits plus `.`/`-` (BRK-B, BRK.B, RDS.A…).
const TICKER_RE = /^[A-Z0-9.-]{1,12}$/

/** Strip anything a ticker can't contain and upper-case. Use on input change. */
export function sanitizeTickerInput(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9.-]/g, '')
}

/** True when `ticker` is a syntactically valid symbol (case-insensitive). */
export function isValidTicker(ticker: string): boolean {
  return TICKER_RE.test(ticker.toUpperCase())
}
