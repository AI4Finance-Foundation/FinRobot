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
 */
export function formatCurrency(
  n: number | null | undefined,
  currency: string,
  locale: Locale,
  digits = 2,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat(NF_LOCALE[locale], {
    style: 'currency',
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

/**
 * Date formatter.
 *   short ⇒ "2026-05-23" (ISO, locale-invariant — consistent for tables/lists)
 *   long  ⇒ "2026年5月23日" (zh) / "May 23, 2026" (en)
 *   datetime ⇒ "2026-05-23 14:30" (zh) / "May 23, 2026, 2:30 PM" (en)
 */
export function formatDate(
  d: Date | string | number | null | undefined,
  locale: Locale,
  style: 'short' | 'long' | 'datetime' = 'short',
): string {
  if (d === null || d === undefined) return '—'
  const date = typeof d === 'string' || typeof d === 'number' ? new Date(d) : d
  if (Number.isNaN(date.getTime())) return '—'

  if (style === 'short') {
    // ISO YYYY-MM-DD — locale-invariant and column-aligned for tables.
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
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
 * Relative-time formatter for short labels like "3 小时前 / 3h ago".
 * Used in artifact timelines and recent-research strips.
 */
export function formatRelativeTime(
  d: Date | string | number | null | undefined,
  locale: Locale,
  now: Date = new Date(),
): string {
  if (d === null || d === undefined) return '—'
  const date = typeof d === 'string' || typeof d === 'number' ? new Date(d) : d
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
