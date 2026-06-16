// Locale-aware formatting helpers for numbers, percents, currency and dates.
//
// Why this exists:
//   Hard-coded `n.toLocaleString()` or `${n.toFixed(2)}` scattered across the
//   codebase make it impossible to honour the active UI locale (zh / en) when
//   the user switches languages. This module centralises every formatting
//   decision so the rest of the UI can pass `locale` and forget the rules.
//
// Conventions:
//   - zh ⇒ groups thousands with comma, large numbers compact to "万 / 亿"
//   - en ⇒ groups thousands with comma, large numbers compact to "K / M / B"
//   - Dates ⇒ ISO "YYYY-MM-DD" short form everywhere; long form follows locale
//   - Currency ⇒ Intl.NumberFormat handles symbol placement ($1.23 vs ￥1.23)

import type { Locale } from '../i18n'
import { tSync } from '../i18n'

const NF_LOCALE: Record<Locale, string> = {
  zh: 'zh-CN',
  en: 'en-US',
}

/** Default-decimals number with grouping. e.g. `1,234.56` */
export function formatNumber(n: number | null | undefined, locale: Locale, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat(NF_LOCALE[locale], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

/**
 * Locale-correct rendering with grouping and Intl default fraction digits
 * (0-3, no padding) — the deterministic replacement for a bare
 * `n.toLocaleString()` (which follows the OS locale, not the UI locale)
 * when the value's precision is caller-owned.
 */
export function formatNumberAuto(n: number | null | undefined, locale: Locale): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat(NF_LOCALE[locale]).format(n)
}

/** Integer with grouping; no fractional part. e.g. `1,234` */
export function formatInteger(n: number | null | undefined, locale: Locale): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat(NF_LOCALE[locale], { maximumFractionDigits: 0 }).format(n)
}

/**
 * Compact large-number formatter.
 *
 *   zh → 12.3 万 / 1.23 亿 / 1.23 万亿
 *   en → 12.3K / 1.23M / 1.23B / 1.23T
 *
 * Below the first threshold falls back to formatInteger.
 */
export function formatCompactNumber(n: number | null | undefined, locale: Locale): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const abs = Math.abs(n)
  if (locale === 'zh') {
    if (abs >= 1e12) return (n / 1e12).toFixed(2) + ' 万亿'
    if (abs >= 1e8) return (n / 1e8).toFixed(2) + ' 亿'
    if (abs >= 1e4) return (n / 1e4).toFixed(1) + ' 万'
    return formatInteger(n, locale)
  }
  if (abs >= 1e12) return (n / 1e12).toFixed(2) + 'T'
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return formatInteger(n, locale)
}

/**
 * Percent formatter. Input is the raw ratio (0.123 → 12.3%) by default.
 * Pass `alreadyPercent: true` if your number is already on the 0-100 scale.
 */
export function formatPercent(
  n: number | null | undefined,
  locale: Locale,
  digits = 1,
  alreadyPercent = false,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const ratio = alreadyPercent ? n / 100 : n
  return new Intl.NumberFormat(NF_LOCALE[locale], {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(ratio)
}

/**
 * Currency formatter. Pass ISO code ('USD', 'CNY', 'HKD').
 * For ticker-aware contexts the caller decides the currency.
 *
 * Graceful fallback: an unknown / non-ISO-4217 code makes Intl throw, so we
 * catch and degrade to a `CODE 1,234.56` prefix (e.g. `XYZ 1,234.56`). We never
 * silently emit '$' for a non-USD currency. Missing currency defaults to USD at
 * the call site (older artifacts), so US reports render byte-identically.
 */
export function formatCurrency(
  n: number | null | undefined,
  currency: string,
  locale: Locale,
  digits = 2,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  try {
    return new Intl.NumberFormat(NF_LOCALE[locale], {
      style: 'currency',
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(n)
  } catch {
    return `${currency} ${formatNumber(n, locale, digits)}`
  }
}

/**
 * Compact currency formatter — the currency-aware sibling of
 * formatCompactNumber. Renders large amounts with the active currency symbol
 * and compact units:
 *   en + USD → $1.23B / $4.5M / $12.3K
 *   zh + USD → $1.23 亿 / $4500 万
 *   HKD      → HK$1.23B (Intl symbol) ; unknown code → `XYZ 1.23B` fallback.
 *
 * Built by suffixing the compact magnitude onto the formatted symbol so the
 * currency symbol placement still honours the locale, then swapping the
 * grouped number for the compact one. Falls through to formatCurrency for
 * sub-thousand values (no compacting needed there).
 */
export function formatCurrencyCompact(
  n: number | null | undefined,
  currency: string,
  locale: Locale,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const abs = Math.abs(n)
  // Below the first compact threshold, defer to the plain currency formatter
  // (locale + symbol placement) — no unit suffix needed.
  const firstThreshold = locale === 'zh' ? 1e4 : 1e3
  if (abs < firstThreshold) return formatCurrency(n, currency, locale, 0)

  // Finance convention puts the sign BEFORE the currency symbol (-$5.00B);
  // compacting the signed value and prefixing "$" yielded "$-5.00B".
  const sign = n < 0 ? '-' : ''
  const compact = formatCompactNumber(abs, locale) // e.g. "1.23B" / "1.23 亿"
  // USD always renders as a bare "$" so existing US reports stay byte-identical
  // (the default `symbol` display would localize it to "US$" under zh).
  if (currency.toUpperCase() === 'USD') return `${sign}$${compact}`
  // Extract the currency symbol via formatToParts (ICU-stable, unlike stripping
  // a formatted string). Default `symbol` display keeps "HK$" distinct from "$"
  // — narrowSymbol would collapse HK$→$, re-introducing the very mislabel
  // BUG-030 fixes. An unknown code surfaces as its raw ISO code, which we space
  // off into a `CODE compact` fallback. Never silently prints "$".
  try {
    const parts = new Intl.NumberFormat(NF_LOCALE[locale], {
      style: 'currency',
      currency,
    }).formatToParts(1)
    const sym = parts.find((p) => p.type === 'currency')?.value ?? currency
    if (sym.toUpperCase() === currency.toUpperCase()) return `${currency} ${sign}${compact}`
    return `${sign}${sym}${compact}`
  } catch {
    return `${currency} ${sign}${compact}`
  }
}

/** Date-only ISO strings ("YYYY-MM-DD") — fiscal period ends, price-bar dates. */
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/

/**
 * Parse a date input for *calendar-day* rendering. `new Date('YYYY-MM-DD')`
 * parses as UTC midnight per spec, so rendering it with the local-TZ getters
 * below shows the PREVIOUS day for any viewer west of UTC (a 2026-03-31
 * fiscal period end renders "2026-03-30" in New York). Date-only strings are
 * therefore parsed as LOCAL midnight so the calendar day always round-trips;
 * everything else (full ISO timestamps, epoch numbers, Date) is a real
 * instant and keeps normal parsing.
 */
function parseDateInput(d: Date | string | number): Date {
  if (typeof d === 'string' && DATE_ONLY_RE.test(d)) {
    const [y, m, day] = d.split('-').map(Number)
    return new Date(y, m - 1, day)
  }
  return typeof d === 'string' || typeof d === 'number' ? new Date(d) : d
}

/**
 * Date formatter.
 *   short ⇒ "2026-05-23" (ISO, locale-invariant — consistent for tables/lists)
 *   long  ⇒ "2026年5月23日" (zh) / "May 23, 2026" (en)
 *   datetime ⇒ "2026-05-23 14:30" (zh) / "May 23, 2026, 2:30 PM" (en)
 *   time ⇒ "14:30" (zh) / "2:30 PM" (en) — minutes-scale moments (breaker
 *          cooldown ends) where the date is implied to be today
 */
export function formatDate(
  d: Date | string | number | null | undefined,
  locale: Locale,
  style: 'short' | 'long' | 'datetime' | 'time' = 'short',
): string {
  if (d === null || d === undefined) return '—'
  const date = parseDateInput(d)
  if (Number.isNaN(date.getTime())) return '—'

  if (style === 'short') {
    // ISO YYYY-MM-DD — locale-invariant and column-aligned for tables.
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }

  if (style === 'time') {
    if (locale === 'zh') {
      const h = String(date.getHours()).padStart(2, '0')
      const min = String(date.getMinutes()).padStart(2, '0')
      return `${h}:${min}`
    }
    return new Intl.DateTimeFormat(NF_LOCALE[locale], {
      hour: 'numeric',
      minute: '2-digit',
    }).format(date)
  }

  if (style === 'long') {
    if (locale === 'zh') {
      return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
    }
    return new Intl.DateTimeFormat(NF_LOCALE[locale], {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }).format(date)
  }

  // datetime
  if (locale === 'zh') {
    const y = date.getFullYear()
    const mo = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const h = String(date.getHours()).padStart(2, '0')
    const min = String(date.getMinutes()).padStart(2, '0')
    return `${y}-${mo}-${day} ${h}:${min}`
  }
  return new Intl.DateTimeFormat(NF_LOCALE[locale], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

/**
 * Render the UTC calendar day of an instant ("2026-06-11" from
 * "2026-06-11T16:20:00Z"), timezone-STABLE. A source-reported timestamp (a news
 * `published`, a filing instant) names a publication DAY; passing the full ISO
 * to formatDate('short') renders it with the viewer's LOCAL getters, so an
 * evening-UTC instant rolls to the next day east of UTC (UTC+8 turned
 * 06-11T16:20Z into "2026-06-12" — a rendered-vs-source mismatch on a
 * traceability surface). Use this for any source date that must match what the
 * source reported regardless of viewer timezone. Date-only "YYYY-MM-DD" inputs
 * already round-trip via parseDateInput, so this also handles them (their UTC
 * getters off a real Date would mis-shift — we detect and pass them through).
 */
export function formatSourceDate(
  d: string | number | Date | null | undefined,
  _locale: Locale,
): string {
  if (d === null || d === undefined) return '—'
  // A bare date-only string is already a calendar day with no instant — keep it
  // verbatim (UTC getters on its local-midnight Date would shift it backwards).
  if (typeof d === 'string' && DATE_ONLY_RE.test(d)) return d
  const dt = d instanceof Date ? d : new Date(d)
  if (Number.isNaN(dt.getTime())) return '—'
  const y = dt.getUTCFullYear()
  const m = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const day = String(dt.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Stale 阈值常量（秒）。> WARN 视为 delayed；> DANGER 视为 stale。 */
export const FRESHNESS_WARN_SECONDS = 5 * 60 // 5min
export const FRESHNESS_DANGER_SECONDS = 30 * 60 // 30min

/**
 * Format ISO8601 timestamp as relative age. Catalog-driven, no zh/en literals.
 * Returns '—' on null / invalid / NaN input.
 */
export function formatAge(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const seconds = Math.max(0, Math.floor((now.getTime() - t) / 1000))
  if (seconds < 5) return tSync('marketdata.age.justNow')
  if (seconds < 60) return tSync('marketdata.age.sAgo', { n: seconds })
  if (seconds < 3600) return tSync('marketdata.age.minAgo', { n: Math.floor(seconds / 60) })
  return tSync('marketdata.age.hAgo', { n: Math.floor(seconds / 3600) })
}

/**
 * Severity color for the TickerHero pulse-dot. Cosmic-spec aligned:
 *   - fresh (≤ 5min):     var(--accent-cyan)  ← live 信号专用色
 *   - delayed (≤ 30min):  var(--warning)
 *   - stale (> 30min):    var(--danger)
 *
 * NOT applied to pill border / text to avoid double signal.
 */
export function freshnessColor(ageSeconds: number): string {
  if (ageSeconds > FRESHNESS_DANGER_SECONDS) return 'var(--danger)'
  if (ageSeconds > FRESHNESS_WARN_SECONDS) return 'var(--warning)'
  return 'var(--accent-cyan)'
}

/**
 * Freshness tier drives the pill LABEL so "近实时" never lies about > 5min data.
 */
export type FreshnessTier = 'fresh' | 'delayed' | 'stale'

export function freshnessTier(ageSeconds: number): FreshnessTier {
  if (ageSeconds > FRESHNESS_DANGER_SECONDS) return 'stale'
  if (ageSeconds > FRESHNESS_WARN_SECONDS) return 'delayed'
  return 'fresh'
}

/**
 * Relative-time formatter for short labels like "3 小时前 / 3h ago".
 * Used in artifact timelines and recent-research strips.
 */
export function formatRelativeTime(
  d: Date | string | number | null | undefined,
  locale: Locale,
  now: Date = new Date(),
): string {
  if (d === null || d === undefined) return '—'
  const date = parseDateInput(d)
  if (Number.isNaN(date.getTime())) return '—'

  const diffMs = now.getTime() - date.getTime()
  const sec = Math.round(diffMs / 1000)
  const min = Math.round(sec / 60)
  const hr = Math.round(min / 60)
  const day = Math.round(hr / 24)

  if (locale === 'zh') {
    if (sec < 60) return '刚刚'
    if (min < 60) return `${min} 分钟前`
    if (hr < 24) return `${hr} 小时前`
    if (day < 30) return `${day} 天前`
    return formatDate(date, locale, 'short')
  }
  if (sec < 60) return 'just now'
  if (min < 60) return `${min} min ago`
  if (hr < 24) return `${hr}h ago`
  if (day < 30) return `${day}d ago`
  return formatDate(date, locale, 'short')
}
