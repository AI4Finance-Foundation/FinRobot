/**
 * Unified financial number formatters.
 * Single source of truth — no more per-component copies.
 */

const EM_DASH = '\u2014'

/** Format a number as USD with abbreviation (T/B/M/K). */
export function fmtUsd(val: number | null | undefined): string {
  if (val == null) return EM_DASH
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
  return `${sign}$${abs.toLocaleString()}`
}

/** Format as percentage (expects 0-1 range, multiplies by 100). */
export function fmtPct(val: number | null | undefined): string {
  if (val == null) return EM_DASH
  return `${(val * 100).toFixed(1)}%`
}

/** Format as percentage (already in 0-100 range, no multiplication). */
export function fmtPctRaw(val: number | null | undefined): string {
  if (val == null) return EM_DASH
  return `${val.toFixed(1)}%`
}

/** Format as multiple (e.g. 12.3x). */
export function fmtMult(val: number | null | undefined): string {
  if (val == null) return EM_DASH
  return `${val.toFixed(1)}x`
}

/** Format as price ($123.45). */
export function fmtPrice(val: number | null | undefined): string {
  if (val == null) return EM_DASH
  return `$${val.toFixed(2)}`
}

/** Format EPS ($1.23). */
export function fmtEps(val: number | null | undefined): string {
  if (val == null) return EM_DASH
  return `$${val.toFixed(2)}`
}

/** Generic financial format — dispatches to specific formatter. */
export function fmt(
  val: number | null | undefined,
  style: 'usd' | 'pct' | 'mult' | 'num' | 'price',
): string {
  if (val == null) return EM_DASH
  switch (style) {
    case 'usd':
      return fmtUsd(val)
    case 'pct':
      return fmtPct(val)
    case 'mult':
      return fmtMult(val)
    case 'price':
      return fmtPrice(val)
    case 'num':
      return val.toLocaleString()
  }
}
