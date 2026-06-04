import { describe, it, expect } from 'vitest'
import {
  formatNumber,
  formatInteger,
  formatCompactNumber,
  formatPercent,
  formatCurrency,
  formatCurrencyCompact,
  formatDate,
  formatRelativeTime,
} from '../format'

describe('format / formatNumber', () => {
  it('groups thousands with commas (zh & en)', () => {
    expect(formatNumber(1234567.89, 'zh')).toBe('1,234,567.89')
    expect(formatNumber(1234567.89, 'en')).toBe('1,234,567.89')
  })
  it('honours digits parameter', () => {
    expect(formatNumber(3.14159, 'en', 3)).toBe('3.142')
    expect(formatNumber(3.14159, 'en', 0)).toBe('3')
  })
  it('returns em-dash for null/undefined/NaN', () => {
    expect(formatNumber(null, 'zh')).toBe('—')
    expect(formatNumber(undefined, 'en')).toBe('—')
    expect(formatNumber(NaN, 'zh')).toBe('—')
  })
})

describe('format / formatInteger', () => {
  it('drops fractional part', () => {
    expect(formatInteger(1234.78, 'en')).toBe('1,235') // bankers round
    expect(formatInteger(1234.78, 'zh')).toBe('1,235')
  })
})

describe('format / formatCompactNumber', () => {
  it('zh maps to 万/亿/万亿', () => {
    expect(formatCompactNumber(15_000, 'zh')).toBe('1.5 万')
    expect(formatCompactNumber(123_000_000, 'zh')).toBe('1.23 亿')
    expect(formatCompactNumber(2_500_000_000_000, 'zh')).toBe('2.50 万亿')
  })
  it('en maps to K/M/B/T', () => {
    expect(formatCompactNumber(1500, 'en')).toBe('1.5K')
    expect(formatCompactNumber(2_500_000, 'en')).toBe('2.50M')
    expect(formatCompactNumber(1_230_000_000, 'en')).toBe('1.23B')
    expect(formatCompactNumber(2_500_000_000_000, 'en')).toBe('2.50T')
  })
  it('handles negative numbers', () => {
    expect(formatCompactNumber(-500_000, 'en')).toBe('-500.0K')
    expect(formatCompactNumber(-1_200_000_000, 'en')).toBe('-1.20B')
    expect(formatCompactNumber(-50_000, 'zh')).toBe('-5.0 万')
  })
  it('small numbers fall back to integer', () => {
    expect(formatCompactNumber(999, 'zh')).toBe('999')
    expect(formatCompactNumber(999, 'en')).toBe('999')
  })
})

describe('format / formatPercent', () => {
  it('treats input as ratio by default (0.12 → 12.0%)', () => {
    expect(formatPercent(0.12, 'en')).toBe('12.0%')
    expect(formatPercent(0.12, 'zh')).toBe('12.0%')
  })
  it('alreadyPercent flag accepts 0-100 input', () => {
    expect(formatPercent(12, 'en', 1, true)).toBe('12.0%')
  })
})

describe('format / formatCurrency', () => {
  it('USD uses $', () => {
    expect(formatCurrency(1234.5, 'USD', 'en')).toContain('$')
    expect(formatCurrency(1234.5, 'USD', 'en')).toContain('1,234.50')
  })
  it('CNY shows ¥', () => {
    const out = formatCurrency(1234.5, 'CNY', 'zh')
    expect(out).toMatch(/[¥￥]/)
  })
  it('falls back to a `CODE amount` prefix for an unknown currency (never $)', () => {
    // ICU renders an unknown 3-letter code as "XYZ<nbsp>1,234.50"; normalize the
    // separator before comparing. The contract that matters: code prefix, no '$'.
    const out = formatCurrency(1234.5, 'XYZ', 'en').replace(/\u00A0/g, ' ')
    expect(out).toBe('XYZ 1,234.50')
    expect(out).not.toContain('$')
  })
})

describe('format / formatCurrencyCompact', () => {
  it('USD renders byte-identically to the legacy `$` + compact convention', () => {
    expect(formatCurrencyCompact(1_230_000_000, 'USD', 'en')).toBe('$1.23B')
    expect(formatCurrencyCompact(4_500_000, 'USD', 'en')).toBe('$4.50M')
    expect(formatCurrencyCompact(123_000_000, 'USD', 'zh')).toBe('$1.23 亿')
  })
  it('honours non-USD symbols (HKD → HK$, never $)', () => {
    const out = formatCurrencyCompact(1_230_000_000, 'HKD', 'en')
    expect(out).toBe('HK$1.23B')
  })
  it('falls back to a `CODE compact` prefix for an unknown currency (never $)', () => {
    const out = formatCurrencyCompact(1_230_000_000, 'XYZ', 'en')
    expect(out).toBe('XYZ 1.23B')
    expect(out).not.toContain('$')
  })
  it('defers to plain currency formatter below the compact threshold', () => {
    expect(formatCurrencyCompact(950, 'USD', 'en')).toBe('$950')
  })
  it('returns em-dash for null/undefined/NaN', () => {
    expect(formatCurrencyCompact(null, 'USD', 'en')).toBe('—')
    expect(formatCurrencyCompact(NaN, 'HKD', 'zh')).toBe('—')
  })
})

describe('format / formatDate', () => {
  const d = new Date(2026, 4, 23, 14, 30) // May 23 2026 14:30 local

  it('short returns ISO YYYY-MM-DD', () => {
    expect(formatDate(d, 'zh', 'short')).toBe('2026-05-23')
    expect(formatDate(d, 'en', 'short')).toBe('2026-05-23')
  })
  it('long zh uses 年月日', () => {
    expect(formatDate(d, 'zh', 'long')).toBe('2026年5月23日')
  })
  it('long en uses Month DD, YYYY', () => {
    const out = formatDate(d, 'en', 'long')
    expect(out).toMatch(/May 23, 2026/)
  })
  it('datetime zh uses YYYY-MM-DD HH:MM', () => {
    expect(formatDate(d, 'zh', 'datetime')).toBe('2026-05-23 14:30')
  })
  it('accepts string ISO input', () => {
    expect(formatDate('2026-05-23T00:00:00Z', 'en', 'short')).toMatch(/2026-05-2[23]/)
  })
  it('invalid date returns em-dash', () => {
    expect(formatDate('not-a-date', 'zh')).toBe('—')
    expect(formatDate(null, 'en')).toBe('—')
  })
})

describe('format / formatRelativeTime', () => {
  const now = new Date(2026, 4, 23, 14, 30)

  it('just now under 60s (en + zh)', () => {
    const d = new Date(now.getTime() - 30 * 1000)
    expect(formatRelativeTime(d, 'en', now)).toBe('just now')
    expect(formatRelativeTime(d, 'zh', now)).toBe('刚刚')
  })
  it('minutes / hours / days', () => {
    expect(formatRelativeTime(new Date(now.getTime() - 5 * 60_000), 'zh', now)).toBe('5 分钟前')
    expect(formatRelativeTime(new Date(now.getTime() - 3 * 3600_000), 'en', now)).toBe('3h ago')
    expect(formatRelativeTime(new Date(now.getTime() - 5 * 86400_000), 'zh', now)).toBe('5 天前')
  })
  it('>30d falls back to absolute date', () => {
    const old = new Date(now.getTime() - 60 * 86400_000)
    const out = formatRelativeTime(old, 'en', now)
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
